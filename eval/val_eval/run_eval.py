import os
import json
import argparse
import logging
import random
import torch
import datasets
import vllm
#from alpaca_eval import evaluate as alpaca_farm_evaluate
from eval.utils import query_openai_chat_model, query_openai_model, generate_completions, dynamic_import_function, load_hf_lm, load_hf_tokenizer

def main(args):
    random.seed(42)
    os.makedirs(args.save_dir, exist_ok=True)

    logging.info("loading data and model...")
    #alpaca_eval_data = datasets.load_dataset(".val.jsonl")
    alpaca_eval_data = datasets.load_dataset("json", data_files="eval/val_eval/val.jsonl")['train']
    prompts = []
    chat_formatting_function = dynamic_import_function(args.chat_formatting_function) if args.use_chat_format else None
    for example in alpaca_eval_data:
        print(example)
        prompt = example["instruction"]
        prompt = args.instruction_prefix + prompt
        prompts.append(prompt)

    if args.model_name_or_path is not None:
        # we always load the tokenizer for vllm or hf models
        tokenizer = load_hf_tokenizer(
                model_name_or_path=args.model_name_or_path,
                tokenizer_name_or_path=args.tokenizer_name_or_path,
                use_fast_tokenizer=not args.use_slow_tokenizer,
            )

        if args.use_vllm:
            model = vllm.LLM(
                model=args.model_name_or_path,
                tokenizer=args.tokenizer_name_or_path if args.tokenizer_name_or_path is not None else args.model_name_or_path,
                tokenizer_mode="slow" if args.use_slow_tokenizer else "auto",
                tensor_parallel_size=torch.cuda.device_count(),
            )
            
            sampling_params = vllm.SamplingParams(
                temperature=0,  # greedy decoding
                max_tokens=args.max_new_tokens,
            )
            # apply chat formatting
            if args.use_chat_format:
                formatted_prompts = []
                for prompt in prompts:
                    messages = [{"role": "user", "content": prompt}]
                    formatted_prompt = chat_formatting_function(messages, tokenizer, add_bos=False)
                    formatted_prompts.append(formatted_prompt)
                prompts = formatted_prompts
                    
            outputs = model.generate(prompts, sampling_params)
            outputs = [it.outputs[0].text for it in outputs]
        else:
            model = load_hf_lm(
                model_name_or_path=args.model_name_or_path,
                load_in_8bit=args.load_in_8bit,
                device_map="balanced_low_0" if torch.cuda.device_count() > 1 else "auto",
                gptq_model=args.gptq,
                add_rule_based_helper=args.add_rule_based_helper,
                tokenizer=tokenizer,
            )
            # modify tokenizer if required
            from transformers import GPTNeoXForCausalLM, OPTForCausalLM
            if isinstance(model, GPTNeoXForCausalLM) or isinstance(model, OPTForCausalLM):
                tokenizer.model_max_length = model.config.max_position_embeddings
                print("Set tokenizer.model_max_length to model.config.max_position_embeddings: {}".format(model.config.max_position_embeddings))

            # apply chat formatting
            if args.use_chat_format:
                formatted_prompts = []
                for prompt in prompts:
                    messages = [{"role": "user", "content": prompt}]
                    formatted_prompt = chat_formatting_function(messages, tokenizer, add_bos=False)
                    formatted_prompts.append(formatted_prompt)
                prompts = formatted_prompts
            outputs = generate_completions(
                model=model,
                tokenizer=tokenizer,
                prompts=prompts,
                max_new_tokens=args.max_new_tokens,
                do_sample=False,
                temperature=0,
                batch_size=args.eval_batch_size if args.eval_batch_size else 1,
            )
    else:
        openai_query_cache_path = os.path.join(args.save_dir, "openai_query_cache.jsonl")
        openai_func = query_openai_model if args.openai_engine == "text-davinci-003" else query_openai_chat_model
        results = openai_func(
            engine=args.openai_engine,
            instances=[{"id": str(i), "prompt": prompt} for i, prompt in enumerate(prompts)],
            batch_size=args.eval_batch_size if args.eval_batch_size else 10,
            output_path=openai_query_cache_path,
            max_tokens=args.max_new_tokens,
            temperature=0,
            reuse_existing_outputs=True,
        )
        outputs = [result["output"] for result in results]

    model_name = os.path.basename(os.path.normpath(args.model_name_or_path)) if args.model_name_or_path is not None else args.openai_engine
    model_results = []
    with open(os.path.join(args.save_dir, f"{model_name}-greedy-long-output.json"), "w") as fout:
        for example, output in zip(alpaca_eval_data, outputs):
            example["output"] = output
            example["generator"] = f"{model_name}-greedy-long"
            #fout.write(json.dumps(example) + "\n")
            model_results.append(example)
        fout.write(json.dumps(model_results))

    #if args.reference_path is not None:
    #    df_leaderboard, annotations = alpaca_farm_evaluate(
    #        model_outputs=model_results,
    #        reference_outputs=args.reference_path,
    #        output_path=args.save_dir,
    #        is_return_instead_of_print=True,
    #        caching_path=os.path.join(args.save_dir, "alpaca_eval_annotator_cache.json"),
    #        precomputed_leaderboard=None,
    #        is_cache_leaderboard=False
    #    )
    #else:
    #    df_leaderboard, annotations = alpaca_farm_evaluate(
    #        model_outputs=model_results,
    #        output_path=args.save_dir,
    #        is_return_instead_of_print=True,
    #        caching_path=os.path.join(args.save_dir, "alpaca_eval_annotator_cache.json"),
    #        precomputed_leaderboard=None,
    #        is_cache_leaderboard=False
    #    )

    #print(df_leaderboard.to_string(float_format="%.2f"))

    ## save to json
    #with open(os.path.join(args.save_dir, f"metrics.json"), "w") as fout:
    #    json.dump(df_leaderboard.to_dict(), fout)
        

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--reference_path",
        type=str,
        default=None,
        help="Path to the reference outputs. "
             "Alpaca_eval leaderboard use text-davinci-003 to generate the reference outputs, "
             "but they limit the max_tokens to 300, which is a bit unfair for text-davinci-003. "
             "Here we keep this default setup to make numbers comparable to their leaderboard. "
             "But you can also use the regenerated reference outputs with max_tokens=2048 "
             "hosted at https://huggingface.co/datasets/hamishivi/alpaca-farm-davinci-003-2048-token.",
    )
    parser.add_argument(
        "--save_dir",
        type=str, 
        default="results/alpaca_farm")
    parser.add_argument(
        "--model_name_or_path",
        type=str,
        default=None,
        help="If specified, we will load the model to generate the predictions.",
    )
    parser.add_argument(
        "--tokenizer_name_or_path",
        type=str,
        default=None,
        help="If specified, we will load the tokenizer from here.",
    )
    parser.add_argument(
        "--use_slow_tokenizer",
        action="store_true",
        help="If given, we will use the slow tokenizer."
    )
    parser.add_argument(
        "--openai_engine",
        type=str,
        default=None,
        help="If specified, we will use the OpenAI API to generate the predictions.",
    )
    parser.add_argument(
        "--max_new_tokens",
        type=int,
        default=8192,
        help="Maximum number of new tokens to generate."
    )
    parser.add_argument(
        "--eval_batch_size", 
        type=int, 
        default=1, 
        help="Batch size for evaluation."
    )
    parser.add_argument(
        "--load_in_8bit",
        action="store_true",
        help="Load model in 8bit mode, which will reduce memory and speed up inference.",
    )
    parser.add_argument(
        "--gptq",
        action="store_true",
        help="If given, we're evaluating a 4-bit quantized GPTQ model.",
    )
    parser.add_argument(
        "--use_chat_format", 
        action="store_true", 
        help="If given, we will use the chat format for the prompts."
    )
    parser.add_argument(
        "--chat_formatting_function", 
        type=str, 
        default="eval.templates.create_prompt_with_tulu_chat_format", 
        help="The function to use to create the chat format. This function will be dynamically imported. Please see examples in `eval/templates.py`."
    )
    parser.add_argument(
        "--use_vllm",
        action="store_true",
        help="If given, we will use vLLM to generate the predictions - much faster.",
    )
    parser.add_argument(
        "--add_rule_based_helper",
        #action="store_true",
        default=False,
        help="If given, we will use vLLM to generate the predictions - much faster.",
    )
    parser.add_argument(
        "--instruction_prefix",
        default="",
        type=str,
        help="String to prepend to all instructions (e.g., for quality specification)",
    )
    args = parser.parse_args()

    # model_name_or_path and openai_engine cannot be both None or both not None.
    assert (args.model_name_or_path is None) != (args.openai_engine is None), "Either model_name_or_path or openai_engine should be specified."
    main(args)
