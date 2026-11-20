"""Create a random, tiny local model to exercise the adapter without downloads.

Run inside a copied example workspace. Never use its scores as model-quality evidence.
"""
from pathlib import Path

import torch
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace
from transformers import GPT2Config, GPT2LMHeadModel, PreTrainedTokenizerFast

target = Path("tiny-model")
if target.exists():
    raise SystemExit("tiny-model already exists; refusing to overwrite a model")
torch.manual_seed(0)
vocab = {word: i for i, word in enumerate(["[UNK]", "[PAD]", "[EOS]", "The", "red", "blue", "cube", "ball", "is"])}
tokenizer = Tokenizer(WordLevel(vocab=vocab, unk_token="[UNK]"))
tokenizer.pre_tokenizer = Whitespace()
wrapped = PreTrainedTokenizerFast(tokenizer_object=tokenizer, unk_token="[UNK]", pad_token="[PAD]", eos_token="[EOS]", model_max_length=64)
model = GPT2LMHeadModel(GPT2Config(vocab_size=len(vocab), n_positions=64, n_ctx=64,
                                n_embd=32, n_layer=1, n_head=2,
                                bos_token_id=2, eos_token_id=2, pad_token_id=1))
model.save_pretrained(target, safe_serialization=True)
wrapped.save_pretrained(target)
print("Created random tiny model for connection tests only.")
