import json
import random

import torch
from loguru import logger
from tqdm import tqdm
from transformers import pipeline, AutoModelForCausalLM, AutoTokenizer, \
    BitsAndBytesConfig

from models.abstract_model import AbstractModel
from models.utils import read_prompt_templates_from_csv, disambiguation_baseline


class GenerationModel(AbstractModel):
    def __init__(self, config):
        super().__init__()

        # Getting parameters from the configuration file
        llm_path = config["llm_path"]
        prompt_templates_file = config["prompt_templates_file"]
        train_data_file = config["train_data_file"]
        use_quantization = config["use_quantization"]

        # Generation parameters
        self.few_shot = config["few_shot"]
        self.batch_size = config["batch_size"]
        self.max_new_tokens = config["max_new_tokens"]

        logger.info(f"Loading the tokenizer `{llm_path}`...")
        self.tokenizer = AutoTokenizer.from_pretrained(
            llm_path,
            padding_side="left",
        )
        if self.tokenizer.pad_token_id is None:
            self.tokenizer.pad_token_id = self.tokenizer.eos_token_id

        logger.info(f"Loading the model `{llm_path}`...")
        if use_quantization:
            bnb_config = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_compute_dtype=torch.float16,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=False,
            )
            self.llm = AutoModelForCausalLM.from_pretrained(
                llm_path,
                device_map="auto",
                quantization_config=bnb_config,
                torch_dtype=torch.float16,
            )
        else:
            self.llm = AutoModelForCausalLM.from_pretrained(
                llm_path,
                device_map="auto"
            )
        self.pipe = pipeline(
            task="text-generation",
            model=self.llm,
            tokenizer=self.tokenizer,
        )

        logger.info(
            f"Reading prompt templates from `{prompt_templates_file}`..."
        )
        self.prompt_templates = read_prompt_templates_from_csv(
            prompt_templates_file)

        logger.info(f"Reading train data from `{train_data_file}`...")
        with open(train_data_file) as f:
            self.train_data = [json.loads(line) for line in f]

        # Instantiate templates with train data
        self.in_context_examples = []

        logger.info("Instantiating in-context examples with train data...")
        for row in self.train_data:
            template = self.prompt_templates[row["Relation"]]
            example = (
                f'{template.format(subject_entity=row["SubjectEntity"])} '
                f'{", ".join(row["ObjectEntities"])}'
            )
            self.in_context_examples.append(example)

    def create_prompt(self, subject_entity: str, relation: str) -> str:
        template = self.prompt_templates[relation]
        if self.few_shot > 0:
            random_examples = random.sample(
                self.in_context_examples,
                min(self.few_shot, len(self.in_context_examples))
            )
        else:
            random_examples = []
        few_shot_examples = "\n".join(random_examples)
        prompt = (f"{few_shot_examples}"
                  f"\n{template.format(subject_entity=subject_entity)}")
        return prompt

    def generate_predictions(self, inputs):
        logger.info("Generating predictions...")
        prompts = [
            self.create_prompt(
                subject_entity=inp["SubjectEntity"],
                relation=inp["Relation"]
            ) for inp in inputs
        ]
        # outputs = self.pipe(
        #     prompts,
        #     batch_size=self.batch_size,
        #     max_new_tokens=self.max_new_tokens,
        # )

        outputs = []
        for i in tqdm(range(0, len(prompts), self.batch_size),
                      total=(len(prompts) // self.batch_size + 1),
                      desc="Generating predictions"):
            prompt_batch = prompts[i:i + self.batch_size]
            output = self.pipe(
                prompt_batch,
                batch_size=self.batch_size,
                max_new_tokens=self.max_new_tokens,
            )
            outputs.extend(output)

        logger.info("Disambiguating entities...")
        results = []
        for inp, output, prompt in tqdm(zip(inputs, outputs, prompts),
                                        total=len(inputs),
                                        desc="Disambiguating entities"):
            wikidata_ids = []

            # Remove the original prompt from the generated text
            qa_answer = output[0]["generated_text"].split(prompt)[
                -1].split("\n")[0].strip()
            qa_entities = qa_answer.split(", ")
            for entity in qa_entities:
                entity = entity.strip()
                if entity.startswith("and "):
                    entity = entity[4:]
                wikidata_id = disambiguation_baseline(entity)
                wikidata_ids.append(wikidata_id)

            result_row = {
                "SubjectEntityID": inp["SubjectEntityID"],
                "SubjectEntity": inp["SubjectEntity"],
                "Relation": inp["Relation"],
                "ObjectEntitiesID": wikidata_ids,
            }
            results.append(result_row)

        return results
