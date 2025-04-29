from transformers import PreTrainedModel, GPT2Config, GPT2LMHeadModel
import torch
from torch import nn

from open_instruct.utils import USER_TAG, ASSISTANT_TAG

agreements = [
    #"Sure",
  #"Ab",
  "Okay",
]
#agreements = []

def score_string(s, tok):
    # Check the first character and apply the scoring rules
    if s == '▁': # Strip potential first space
      return 0
    if s[0] == '▁': # Strip potential first space
        s = s[1:] 
    if s == 'I':
      return -3
    if s in agreements:
      return 10
    if s[0].isupper():
        return 1
    elif s[0].islower() or ('\u4e00' <= s[0] <= '\u9fff'):  # Chinese characters
        return 1
    elif ('\u0400' <= s[0] <= '\u04FF' or  # Cyrillic characters
          '\u3040' <= s[0] <= '\u30FF' or  # Japanese Hiragana and Katakana characters
          '\uAC00' <= s[0] <= '\uD7AF'):   # Korean Hangul characters
        return 1
    elif s[0] in ".,:;!?<>[]{}()\"'`~@#$%^&*-=+\\|/":
        return -1
    else:
        return 0

class InsTunerModel(nn.Module):

  def __init__(self, tokenizer, magic_string=None, vocab_size=32000, device='cuda', eos_id=2):
    super().__init__()
    
    self.initial_tokens = []
    #self.soft_eos_range = (100, 200)
    self.soft_eos_range = (50, 400)
    self.hard_eos_range = (1000, 1500)
    self.eos_range = (0, 250)
    self.tokenizer = tokenizer
    self.vocab_size = vocab_size
    self.device = device
    self.register_initial_tokens(tokenizer)
    self.scale = 5
    self.initial_weight = 5
    self.eos_id = eos_id

    self.do_eos_rule = True
    self.do_diversity_rule = True
    self.do_start_rule = True
    self.do_uniform_rule = True
    if isinstance(magic_string, str): 
      self.do_eos_rule = 'eos' in magic_string
      self.do_diversity_rule = 'diversity' in magic_string
      self.do_start_rule = 'start' in magic_string
      self.do_uniform_rule = 'uniform' in magic_string
      # self.do_ablation_rule = 'ablation' in magic_string

  def register_initial_tokens(self, tokenizer):
    vec = torch.tensor(self.vocab_size)
    inverse_map = {v:k for k, v in tokenizer.vocab.items()}
    scores = [score_string(inverse_map[i], tokenizer) for i in range(self.vocab_size)]
    vec = torch.tensor(scores).to(self.device).float()
    self.initial_tok = vec
    self.initial_tok.requires_grad = False

    #def forward(self, input_ids, attention_mask=None, position_ids=None, inputs_embeds=None, labels=None, use_cache=None,
    #            output_attentions=None, output_hidden_states=None, return_dict=True, past_key_values=None, cache_position=None):

    #    if self.do_uniform_rule:
    #      # Uniform token changes (Rule 2)
    #      output = torch.zeros(self.vocab_size).to(input_ids.device)
    #      output[29966], output[529], output[29989] = -4, -4, -4
    #      output[306], output[29902], output[1334], output[5618], output[881] = -5, -5, -3, -5, -6
    #      output[334], output[448], output[1678], output[396], output[444], output[13] = 1, 1, 1, 1, 1, 1
    #      output[29991] = 1

    #      assistant_start_tag = self.tokenizer(f'\n{ASSISTANT_TAG}\n')['input_ids'][-5:]
    #      user_start_tag = self.tokenizer(f'\n{USER_TAG}\n')['input_ids'][-5:]

    #      idlist = input_ids[0].tolist()
    #      first_token_index = next((i + 5 for i in range(len(idlist)) if idlist[i:i + 5] == user_start_tag), None)

    #    # Type repetition penalty (Rule 4)
    #    uniq_words = set(idlist[first_token_index:])
    #    for w in uniq_words:
    #        output[w] -= 1.5

    #    prefix_len = input_ids.shape[-1] - next(i + 5 for i in range(len(idlist)) if idlist[i:i + 5] == assistant_start_tag)

    #    # Say "Okay!" and then not "\n" (Rule 1)
    #    if torch.all(input_ids[0][-5:] == torch.tensor(assistant_start_tag).to(input_ids.device)):
    #        output[20419] += 50
    #    if torch.all(input_ids[0][-6:-1] == torch.tensor(assistant_start_tag).to(input_ids.device)):
    #        output[29991] += 15
    #    if torch.all(input_ids[0][-7:-2] == torch.tensor(assistant_start_tag).to(input_ids.device)):
    #        output[13] -= 10

    #    # Gradually increase EOS. (Rule 3)
    #    if self.eos_range[0] < prefix_len < self.eos_range[1]:
    #        score = max(0, self.scale * (prefix_len - self.eos_range[0]) / (self.eos_range[1] - self.eos_range[0]))
    #        output[self.eos_id] = score * 3
    #    if prefix_len > 1024:
    #        output[self.eos_id] = 100

    #    # Prepare for concatenation with LM output
    #    output = output.unsqueeze(0)
    #    pad = torch.zeros(input_ids.shape[-1] - 1, self.vocab_size).to(output.device)
    #    output = torch.cat((pad, output), dim=0)
    #    output = output.unsqueeze(0).expand(input_ids.shape[0], -1, -1)

    #    class A:
    #        pass

    #    ret = A()
    #    ret.logits = output

    #    return ret

  def forward(self,
      input_ids,
      attention_mask=None,
      position_ids=None,
      inputs_embeds=None,
      labels=None,
      use_cache=None,
      output_attentions=None,
      output_hidden_states=None,
      return_dict=True,
      past_key_values=None,
      cache_position=None,
      ):

    output =  torch.zeros(self.vocab_size).to(input_ids.device)

    if self.do_uniform_rule:
      #### All positions biases (Rule 2)
      ## _< and < and | characters
      ## These characters tend to be used to make formatting decisions like <|#|> or <|$|>
      ## Which are highly likely because they showed up in the prompt, but we don't want them
      output[29966] = -4
      output[529] = -4
      output[29989] = -4

      ## The words I/We/What tend to be used to either continue the request (instead of answering)
      # or to indicate that the model doesn't know (erroneously.)

      # The word "_I" and "I"
      output[306] = -5
      # Somehow the word "I" again??? maybe after a newline
      output[29902] = -5
      # The word "We"
      output[1334] = -3 
      # The word "_What"
      output[5618] = -5
      # Never say "should"
      output[881] = -6

      # Formatting -- increase the probability of nice formatting decisions.
      output[334] = 1 # Increase prob of "-"
      output[448] = 1 # Increase prob of "*"
      output[1678] = 1 # Increase prob of "  " (double space)
      output[396] = 1 # Increase prob of "#"
      output[444] = 1 # Increase prob of "##"
      output[13] = 1 # Increase prob of "\n"


      # Exclamation point for more agreement!
      #output[1738] = 1
      output[29991] = 1
      ### END All token bisaes

    #assistant_start_tag = [29966, 25183, 29989, 29958, 13] #<|$|>
    assistant_start_tag = self.tokenizer(f'\n{ASSISTANT_TAG}\n')['input_ids'][-5:]
    #print(assistant_start_tag)
    #user_start_tag = [529, 29989, 29992, 29989, 29958, 13] #<|@|>
    user_start_tag = self.tokenizer(f'\n{USER_TAG}\n')['input_ids'][-5:]
    #print(user_start_tag)


    # Find tokens
    idlist = input_ids[0].tolist()
    first_token_index = None
    for i in range(len(idlist)):
      if idlist[i:i+5] == user_start_tag:
        first_token_index = i+5
    #print('First token', self.tokenizer.convert_ids_to_tokens(first_token))

    if self.do_diversity_rule:
      # De-weight all words so far
      uniq_words = set()
      for i in range(len(idlist)):
        if i < first_token_index:
          continue
        uniq_words.add(idlist[i])
      for w in uniq_words:
        output[w] -= 1.5



    # Determine length of non-prompt prefix
    prefix_len = input_ids.shape[-1]
    idlist = input_ids[0].tolist()
    for i in range(len(idlist)):
      if idlist[i:i+5] == assistant_start_tag:
        prompt_len = i+5
    prefix_len = prefix_len - prompt_len

    if self.do_start_rule:
      # First token -- Say " Okay"
      if torch.all(input_ids[0][-5:] == torch.tensor(assistant_start_tag).to(input_ids.device)):
        output += self.initial_tok*self.initial_weight # 

      # Second token Say "!"
      if torch.all(input_ids[0][-6:-1] == torch.tensor(assistant_start_tag).to(input_ids.device)):
        output[29991] += 15

      # Don't make a newline after " Okay!"
      if torch.all(input_ids[0][-7:-2] == torch.tensor(assistant_start_tag).to(input_ids.device)):
        output[13] += -10


    if self.do_eos_rule:
      ## EOS bias
      if self.eos_range[0] < prefix_len < self.eos_range[1]:
        score = max(0, self.scale*(prefix_len - self.eos_range[0])/(self.eos_range[1]-self.eos_range[0]))
        vec = torch.zeros(self.vocab_size).to(input_ids.device)
        vec[self.eos_id] = score*3
        output += vec
      if prefix_len >1024:
        vec = torch.zeros(self.vocab_size).to(input_ids.device)
        vec[self.eos_id] = 100


    # Formatting the output distribution
    # Pad with distributions for previous tokens
    output = output.unsqueeze(0)
    pad = torch.zeros(input_ids.shape[-1]-1, self.vocab_size).to(output.device)
    output = torch.cat((pad, output), dim=0)

    # Expand to batch size
    output = output.unsqueeze(0).expand(input_ids.shape[0], -1, -1)

    class A():
      pass
    ret = A()
    ret.logits = output

    return ret


class CombinedCausalLM(GPT2LMHeadModel):
    def __init__(self, model1, model2):
        # Initialize with a dummy config. The actual configs of the individual models are not directly used here.
        super().__init__(GPT2Config())
        
        # Load the two models. These should be compatible with causal language modeling (e.g., GPT-2).
        self.model1 = model1
        self.model2 = model2
        
        # Ensure both models are in the same mode (train/eval) during forward passes.
        self.model1.eval()
        self.model2.eval()
        self.generation_config = self.model1.generation_config
        self.generation_config.use_cache = False
        self.prepare_inputs_for_generation = self.model1.prepare_inputs_for_generation
        self.lm_head = self.model1.lm_head
        self.to(model1.device)

    def forward(self,
        input_ids,
        attention_mask=None,
        position_ids=None,
        inputs_embeds=None,
        labels=None,
        use_cache=None,
        output_attentions=None,
        output_hidden_states=None,
        return_dict=True,
        past_key_values=None,
        cache_position=None,
        ):

        # Run forward pass for both models
        outputs1 = self.model1(input_ids=input_ids, attention_mask=attention_mask, position_ids=position_ids, labels=labels, use_cache=use_cache, output_attentions=output_attentions, output_hidden_states=output_hidden_states, return_dict=True, past_key_values=past_key_values, cache_position=cache_position)
        outputs2 = self.model2(input_ids=input_ids, attention_mask=attention_mask, position_ids=position_ids, labels=labels, use_cache=use_cache, output_attentions=output_attentions, output_hidden_states=output_hidden_states, return_dict=True, past_key_values=past_key_values, cache_position=cache_position)
        
        logits1 = outputs1.logits.log_softmax(dim=-1)
        logits2 = outputs2.logits.log_softmax(dim=-1).to(dtype=logits1.dtype)
        if logits1.shape[-1] != logits2.shape[-1]:
          minshape = min(logits1.shape[-1],logits2.shape[-1])
          logits1 = logits1[:,:,:minshape]
          logits2 = logits2[:,:,:minshape]
        combined_logits =  logits1 + logits2
       
        # You might need to adjust the output depending on whether you want to return a dict or not.
        if return_dict:
            outputs1['logits'] = combined_logits
            return outputs1
        else:
            return (combined_logits,) + outputs1[1:]
