# Entry for LM-KBC: Knowledge Base Construction from Pre-trained Language Models (3rd Edition)

This repository hosts the implementation for the paper "Navigating Nulls, Numbers and Numerous Entities: Robust Knowledge Base Construction from Large Language Models".

This repository is a fork of the official LM-KBC challenge at ISWC
2024 repository (https://github.com/lm-kbc/dataset2024).

This repository contains:

- Our model pipeline - see models/dual_llama_3_chat
- Various prompts used in our experiments - see prompt_templates/
- Config file for with our final pipeline settings
- Code for generating additional contextual information - see data/Generating_contextual_information.ipynb

#### To run our implementation:

Config
file: [configs/custom-llama-3-8b-instruct.yaml](configs/custom-llama-3-8b-instruct.yaml)

```bash
python baseline.py -c configs/custom-llama-3-8b-instruct.yaml -i data/val.jsonl
python evaluate.py -g data/val.jsonl -p output/configs/custom-llama-3-8b-instruct.jsonl
```
