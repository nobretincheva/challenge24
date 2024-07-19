import json
import random
import regex
import ast
import string
import pandas as pd

from loguru import logger
from tqdm import tqdm

from models.baseline_llama_3_chat_model import Llama3ChatModel

class Llama3DualPrompt(Llama3ChatModel):
    def __init__(self, config):
        assert config["llm_path"] in [
            "meta-llama/Meta-Llama-3-8B-Instruct",
            "meta-llama/Meta-Llama-3-70B-Instruct"
        ], (
            "The Llama3ChatModel class only supports the "
            "Meta-Llama-3-8B-Instruct "
            "and Meta-Llama-3-70B-Instruct models."
        )

        super().__init__(config=config)

        self.system_message = (
            "Given a question, your task is to recall anything you know about it first. Answer the question by giving an explanation and then provide just the direct answer as a list (e.g. [Yes] or [2023]). "
            "If the question can be answered simply with a yes or no - response should only be [Yes] or [No] respectively."
            "If the question can be answered with a number - write out only the number e.g. [35]."
            "If there are multiple answers, separate them with a comma. "
            "If there are no answers, leave the list empty. "
            "Your final/direct answer should be on the last line and should be formatted like a list. Your final answer should look like this: final_answer = [YOUR FINAL ANSWER HERE]. ")

        self.terminators = [
            self.pipe.tokenizer.eos_token_id,
            self.pipe.tokenizer.convert_tokens_to_ids("<|eot_id|>")
        ]

        add_info_file = config["add_info_file"]
        self.add_info_df = pd.read_csv(add_info_file).set_index('Relation')




    def create_prompt(self, subject_entity: str, relation: str,
                      entity_entry, info_strategy, stage = 0, reask = "") -> str:
        templates = self.prompt_templates[relation].split(',')
        template = templates[stage]

        persona = self.add_info_df.loc[relation, 'personas']
        extra_input = [tup[1] for tup in string.Formatter().parse(persona) if tup[1] is not None]
        if extra_input:
          persona = persona.format(entity=subject_entity)


        # No few shot implementation for now
        # random_examples = []
        # if self.few_shot > 0:
        #     pool = [example["messages"] for example in self.in_context_examples
        #             if example["relation"] == relation]
        #     # pool = [example["messages"] for example in self.in_context_examples]
        #     random_examples = random.sample(
        #         pool,
        #         min(self.few_shot, len(pool))
        #     )

        messages = [
            {
                "role": "system",
                "content": persona + self.system_message
            }
        ]

        # for example in random_examples:
        #     messages.extend(example)
        question = template.format(subject_entity=subject_entity)
        if not reask:
          question = "Question: " + question + reask

        messages.append({
            "role": "user",
            "content": self.add_external_info(entity_entry, info_strategy) + question
        })

        prompt = self.pipe.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )

        return prompt

    def add_external_info(self, entity_entry, info_strategy):

      system_prompt = ""
      relation_type = entity_entry["Relation"]
      subject_entity=entity_entry["SubjectEntity"]

      for strategy in info_strategy:
        prompt = self.add_info_df.loc[relation_type, strategy + 'Prompt']
        info = entity_entry[strategy]
        if not pd.isnull(info):
          formatted_prompt = prompt.format(entity=subject_entity, info=info)
          system_prompt = system_prompt + formatted_prompt + '\n'

      return system_prompt


    def combine_lists(self, list1, list2):
      return list1 or list2 or list1 + list2
        
    def clean_output(self, output, prompt):
      # returns a list of the answers generated by the prompt
      clean_output = output[0]["generated_text"][len(prompt):].strip()
      matches_underscore = regex.findall(r'final_answer\s?=\s?\[([^\]]*)\]', clean_output)
      matches_space = regex.findall(r'Final answer\s?[=?:?]\s?\[([^\]]*)\]', clean_output)
      
      matches_combined = self.combine_lists(matches_underscore, matches_space)
      matches_none = regex.findall(r'[Aa]nswer\s?[\w*\s?]*:\s?\[([^\]]*)\]', clean_output)                 
      
      final_combined = self.combine_lists(matches_combined, matches_none)
      # edge case: sometimes LLM will answer Yes/No questions with Yes/No followed by the answer itself
      final_combined = [m[:3] if m.startswith('Yes') or m.startswith('yes') else m for m in final_combined]
      # drop any empty lists
      final_combined = [x for x in final_combined if x != []]
      return final_combined


    def use_looping_prompts(self, inp, info_strategy):
      # strategy used for seriesHasNumberOfEpisodes and awardWonBy
      prompt_further_info = self.create_prompt(
                subject_entity=inp["SubjectEntity"],
                relation=inp["Relation"],
                entity_entry=inp,
                info_strategy=info_strategy,
                stage=2
            )

      output = self.pipe(
                prompt_further_info,
                max_new_tokens=self.max_new_tokens,
                eos_token_id=self.terminators,
            )
      further_info = self.clean_output(output, prompt_further_info)
      if not further_info:
        response_only = output[0]["generated_text"][len(prompt_further_info):].strip()
        new_response = self.re_ask_model(prev_answer=response_only,
                                        relation=inp["Relation"], 
                                        entity_entry=inp, 
                                        info_strategy=info_strategy, 
                                        stage=2, 
                                        subject_entity=inp["SubjectEntity"])
        if not new_response:
          return []
        else:
          further_info = new_response

      try:
        answer = further_info[0]

        # this is an ugly way to implement this so far
        # TODO: implement in a less hard-coded way
        start_count = int(answer) if inp["Relation"]=='awardWonBy' else 1
        end_count = int(answer) if inp["Relation"]=='seriesHasNumberOfEpisodes' else 2024

        final_answer = []
        running_sum = 0
        for i in range(start_count, end_count):
          extra_info = str(i) + ' ' if inp["Relation"]=='awardWonBy' else str(i) + ' of '
          if inp["Relation"]=='seriesHasNumberOfEpisodes':
            
            prompt = self.create_prompt(
                subject_entity= extra_info + inp["SubjectEntity"],
                relation=inp["Relation"],
                entity_entry=inp,
                info_strategy=info_strategy,
                stage=1
            )
            output = self.pipe(
                        prompt,
                        max_new_tokens=self.max_new_tokens,
                        eos_token_id=self.terminators,
                    )
            ith_answer = self.clean_output(output, prompt)
            print('Loop ' + str(i) + ': ' + output[0]["generated_text"][len(prompt):].strip())

            int_answers = [num for num in ith_answer if num.isdigit()] 
            if not int_answers:
              response_only = output[0]["generated_text"][len(prompt):].strip()
              ith_answer = self.re_ask_model(prev_answer=response_only,
                                        relation=inp["Relation"], 
                                        entity_entry=inp, 
                                        info_strategy=info_strategy, 
                                        stage=1, 
                                        subject_entity=extra_info + inp["SubjectEntity"])
            try:
              if ith_answer:
                num_ep_per_season = int(ith_answer[0])
                running_sum += num_ep_per_season
            except:
              logger.error(f"Error getting number of episodes for season {i} of " + inp["SubjectEntity"])
          else:
            ith_answer = self.use_dual_prompting(inp, info_strategy=info_strategy, extra_info=extra_info)
            final_answer.append(ith_answer)

        return [str(running_sum)] if inp["Relation"]=='seriesHasNumberOfEpisodes' else final_answer
      except:
        print('could not convert')
        return []


    def re_ask_model(self, prev_answer, relation, entity_entry, info_strategy, stage, subject_entity):
      repeat_prompt =  """
      Answer: {answer}. 
      This answer is not formatted properly. Provide just the direct answer as a list (e.g. [Yes] or [2023]).
      If the question can be answered with a number - write out only the number e.g. [35].
      If there are multiple answers, separate them with a comma. 
      If you believe that the answer is incorrect, also use your expertiese to correct it.
      Your final/direct answer should be on the last line and should be formatted like a list. Your final answer should look like this: final_answer = [YOUR FINAL ANSWER HERE]. """

      prompt = self.create_prompt(
                subject_entity=subject_entity,
                relation=relation,
                entity_entry=entity_entry,
                info_strategy=info_strategy,
                stage=stage,
                reask=repeat_prompt.format(answer = prev_answer)
                )

      output = self.pipe(
                prompt,
                max_new_tokens=self.max_new_tokens,
                eos_token_id=self.terminators,
            )
      new_answer = self.clean_output(output, prompt)
      print('Asking again: ' + output[0]["generated_text"][len(prompt):].strip())

      return new_answer

    def use_dual_prompting(self, inp, info_strategy, extra_info=''):
      # this strategy is split into two steps: the first asks the LLM a yes/no question
      # that helps us narrow down the answer / handle nulls

      # first prompt is a yes/no question
      first_prompt = self.create_prompt(
                subject_entity= extra_info + inp["SubjectEntity"],
                relation=inp["Relation"],
                entity_entry=inp,
                info_strategy=info_strategy,
                stage=0
            )

      output = self.pipe(
                first_prompt,
                max_new_tokens=self.max_new_tokens,
                eos_token_id=self.terminators,
            )
      second_phase = self.clean_output(output, first_prompt)

      print('Output 1: ' + output[0]["generated_text"][len(first_prompt):].strip())
      
      if not second_phase:
        response_only = output[0]["generated_text"][len(first_prompt):].strip()
        new_response = self.re_ask_model(prev_answer=response_only,
                                        relation=inp["Relation"], 
                                        entity_entry=inp, 
                                        info_strategy=info_strategy, 
                                        stage=0, 
                                        subject_entity=extra_info + inp["SubjectEntity"])
        if not new_response:
          return []
        else:
          second_phase = new_response
      
      if second_phase[0].lower() == 'yes':
        second_prompt = self.create_prompt(
                subject_entity=extra_info + inp["SubjectEntity"],
                relation=inp["Relation"],
                entity_entry=inp,
                info_strategy=info_strategy,
                stage=1
                )
        output = self.pipe(
                second_prompt,
                max_new_tokens=self.max_new_tokens,
                eos_token_id=self.terminators,
            )
        
        print('Output 2: ' + output[0]["generated_text"][len(second_prompt):].strip())

        final_result = self.clean_output(output, second_prompt)

        if not final_result:
          response_only = output[0]["generated_text"][len(second_prompt):].strip()
          return self.re_ask_model(prev_answer=response_only,
                                        relation=inp["Relation"], 
                                        entity_entry=inp, 
                                        info_strategy=info_strategy, 
                                        stage=1, 
                                        subject_entity=extra_info + inp["SubjectEntity"])
        else:
          return final_result
      else:
        return []

    def direct_strategy(self, inp, info_strategy):
      prompt = self.create_prompt(
                subject_entity=inp["SubjectEntity"],
                relation=inp["Relation"],
                entity_entry=inp,
                info_strategy=info_strategy,
                stage=3
            )

      output = self.pipe(
                prompt,
                max_new_tokens=self.max_new_tokens,
                eos_token_id=self.terminators,
            )
      further_info = self.clean_output(output, prompt)
      further_info = [num for num in further_info if num.isdigit()] 

      if not further_info:
        response_only = output[0]["generated_text"][len(prompt):].strip()
        new_response = self.re_ask_model(prev_answer=response_only,
                                        relation=inp["Relation"], 
                                        entity_entry=inp, 
                                        info_strategy=info_strategy, 
                                        stage=3, 
                                        subject_entity=inp["SubjectEntity"])
        if not new_response:
          return []
        else:
          further_info = new_response
      
      return further_info

    def generate_predictions(self, inputs):
        # hard coding for now; add with an input variable later on OR add to the prompts doc
        info_strategy = ['additionalData', 'wikipediaExtract']
        logger.info("Generating predictions...")
        exec_strategy = {'awardWonBy': self.use_looping_prompts,
        'seriesHasNumberOfEpisodes': self.direct_strategy,
        'countryLandBordersCountry': self.use_dual_prompting,
        'companyTradesAtStockExchange': self.use_dual_prompting,
        'personHasCityOfDeath': self.use_dual_prompting,}

        results = []
        for inp in tqdm(inputs, desc="Generating predictions"):

            qa_answer = exec_strategy[inp["Relation"]](inp, info_strategy=info_strategy) 

            wikidata_ids = self.disambiguate_entities(list(set(qa_answer)))
            results.append({
                "SubjectEntityID": inp["SubjectEntityID"],
                "SubjectEntity": inp["SubjectEntity"],
                "Relation": inp["Relation"],
                "ObjectEntitiesID": wikidata_ids,
            })

        return results

    def is_valid_wikidata_id(self, wiki_id):
      return wiki_id.startswith("Q")


    def disambiguate_entities(self, qa_answer: str):
        wikidata_ids = []
        qa_entities = [a.split(',') for a in qa_answer]
        flat_entities = [x for xs in qa_entities for x in xs]

        for entity in flat_entities:
            # further clean up string
            entity = entity.strip()
            entity = entity.replace('"', '')
            entity = entity.replace(')', '')

            # handle edge case for stock exchanges
            split_entity = entity.split('(')
            if len(split_entity) > 1:
              wikidata_id_part1 = self.disambiguation_baseline(split_entity[0])
              wikidata_id_part2 = self.disambiguation_baseline(split_entity[1])
              if wikidata_id_part1 == wikidata_id_part2 or self.is_valid_wikidata_id(wikidata_id_part1):
                wikidata_ids.append(wikidata_id_part1)
              elif self.is_valid_wikidata_id(wikidata_id_part2):
                wikidata_ids.append(wikidata_id_part2)
              else:
                wikidata_ids.append(entity)
            else:
              if entity.startswith("and "):
                  entity = entity[4:].strip()
              wikidata_id = self.disambiguation_baseline(entity)
              if wikidata_id:
                  wikidata_ids.append(wikidata_id)
        return wikidata_ids
