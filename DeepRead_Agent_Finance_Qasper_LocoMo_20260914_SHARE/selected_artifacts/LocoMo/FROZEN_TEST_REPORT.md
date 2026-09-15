# LocoMo autonomous single tool: frozen conversation-disjoint Test

## Protocol

- Conversation documents were split 6/2/2 across Train/Dev/Test.
- Every question searched the same complete ten-conversation corpus.
- Analyzer generated one capability from Train; Repair used Dev feedback once to revise that same tool.
- Dev selected v1 or v2; one tool, its usage policy, Student, Judge, inventory and Test split were then frozen.
- Selected variant: `tool_v2_dev_repaired`
- Candidate SHA-256: `cc783c69327b673d5b3c58b98b507f1e240e2598e83ccad17b08caaf885da294`

## Overall results

| Arm | Accuracy | Mean score | Input tokens/q | Output tokens/q | Latency/q | Recall |
|---|---:|---:|---:|---:|---:|---:|
| Baseline | 86.75% | 3.470 | 81832 | 1976 | 44.5s | 94.72% |
| Frozen autonomous tool | 90.00% | 3.600 | 53544 | 1625 | 28.2s | 93.10% |

Paired: **12 wins / 83 ties / 5 losses**, net **+13**.
Tool use: **170 calls across 89/100 questions**.
Accuracy change: **+3.25%**.
Input-token change: **-34.57%**.
Latency change: **-36.60%**.

## Results by official LocoMo category

| Category | Questions | Baseline | Tool | Change |
|---|---:|---:|---:|---:|
| 1 | 16 | 56.25% | 60.94% | +4.69% |
| 2 | 21 | 91.67% | 94.05% | +2.38% |
| 3 | 5 | 85.00% | 80.00% | -5.00% |
| 4 | 58 | 93.53% | 97.41% | +3.88% |

## Per-question changes

| case_id | conversation | Baseline | Tool | Delta | Question |
|---|---|---:|---:|---:|---|
| conv-44::q0061 | conv-44 | 0 | 4 | +4 | Which specific type of bird mesmerizes Andrew? |
| conv-44::q0002 | conv-44 | 0 | 2 | +2 | What kind of indoor activities has Andrew pursued with his girlfriend? |
| conv-44::q0004 | conv-44 | 0 | 2 | +2 | When did Audrey make muffins for herself? |
| conv-48::q0015 | conv-48 | 2 | 4 | +2 | What pets does Jolene have? |
| conv-48::q0093 | conv-48 | 2 | 4 | +2 | What projects is Jolene planning for next year? |
| conv-44::q0017 | conv-44 | 1 | 2 | +1 | How many times did Audrey and Andew plan to hike together? |
| conv-48::q0001 | conv-48 | 3 | 4 | +1 | Which of Deborah`s family and friends have passed away? |
| conv-48::q0008 | conv-48 | 3 | 4 | +1 | What helped Deborah find peace when grieving deaths of her loved ones? |
| conv-48::q0014 | conv-48 | 2 | 3 | +1 | What were Deborah's mother's hobbies? |
| conv-48::q0061 | conv-48 | 3 | 4 | +1 | What projects is Jolene planning for next year? |
| conv-48::q0099 | conv-48 | 3 | 4 | +1 | What do Deborah and Jolene plan to try when they meet in a new cafe? |
| conv-48::q0108 | conv-48 | 3 | 4 | +1 | What new outlook did Jolene gain after her mini retreat on 9 February, 2023? |
| conv-44::q0000 | conv-44 | 4 | 4 | +0 | Which year did Audrey adopt the first three of her dogs? |
| conv-44::q0001 | conv-44 | 4 | 4 | +0 | When did Andrew start his new job as a financial analyst? |
| conv-44::q0003 | conv-44 | 2 | 2 | +0 | What kind of places have Andrew and his girlfriend checked out around the city? |
| conv-44::q0005 | conv-44 | 1 | 1 | +0 | When did Audrey see a hummingbird? |
| conv-44::q0006 | conv-44 | 4 | 4 | +0 | When did Audrey adopt Pixie? |
| conv-44::q0007 | conv-44 | 4 | 4 | +0 | How many years passed between Audrey adopting Pixie and her other three dogs? |
| conv-44::q0008 | conv-44 | 4 | 4 | +0 | Did Andrew have a pet dog during March 2023? |
| conv-44::q0009 | conv-44 | 2 | 2 | +0 | What kind of classes or groups has Audrey joined to take better care of her dogs? |
| conv-44::q0010 | conv-44 | 4 | 4 | +0 | When did Audrey's positive reinforcement training course for dogs take place? |
| conv-44::q0012 | conv-44 | 2 | 2 | +0 | What outdoor activities has Andrew done other than hiking in nature? |
| conv-44::q0014 | conv-44 | 4 | 4 | +0 | What is something that Andrew really misses while working in the city? |
| conv-44::q0015 | conv-44 | 4 | 4 | +0 | What is a shared frustration regarding dog ownership for Audrey and Andrew? |
| conv-44::q0018 | conv-44 | 0 | 0 | +0 | Where did Audrey get Pixie from? |
| conv-44::q0020 | conv-44 | 4 | 4 | +0 | Which meat does Audrey prefer eating more than others? |
| conv-44::q0021 | conv-44 | 2 | 2 | +0 | What are the classes that Audrey took for her dogs to? |
| conv-44::q0062 | conv-44 | 4 | 4 | +0 | What did Andrew express missing about exploring nature trails with his family's dog? |
| conv-44::q0063 | conv-44 | 4 | 4 | +0 | What kind of pastries did Andrew and his girlfriend have at the cafe? |
| conv-44::q0064 | conv-44 | 0 | 0 | +0 | What kind of flowers does Audrey have a tattoo of? |
| conv-44::q0065 | conv-44 | 4 | 4 | +0 | What does Audrey do during dog playdates in the park? |
| conv-44::q0066 | conv-44 | 4 | 4 | +0 | What type of dog was Andrew looking to adopt based on his living space? |
| conv-44::q0067 | conv-44 | 4 | 4 | +0 | Where does Andrew want to live to give their dog a large, open space to run around? |
| conv-44::q0068 | conv-44 | 4 | 4 | +0 | Why did Audrey sign up for a workshop about bonding with pets? |
| conv-44::q0069 | conv-44 | 4 | 4 | +0 | How did Audrey hear about the workshop on bonding with pets? |
| conv-44::q0070 | conv-44 | 4 | 4 | +0 | What type of training was the workshop Audrey signed up for in May 2023? |
| conv-44::q0071 | conv-44 | 4 | 4 | +0 | How did Audrey describe she dog he met at the pet store? |
| conv-44::q0072 | conv-44 | 4 | 4 | +0 | Why did Audrey think positive reinforcement training is important for pets? |
| conv-44::q0073 | conv-44 | 4 | 4 | +0 | What challenge is Andrew facing in their search for a pet? |
| conv-44::q0074 | conv-44 | 4 | 4 | +0 | How does Andrew feel about their search for a pet-friendly place? |
| conv-44::q0075 | conv-44 | 4 | 4 | +0 | What outdoor activities does Andrew plan on trying after the rock climbing class? |
| conv-44::q0076 | conv-44 | 4 | 4 | +0 | How long does Audrey typically walk her dogs for? |
| conv-44::q0077 | conv-44 | 4 | 4 | +0 | What did Audrey set up in the backyard for their dogs on June 26, 2023? |
| conv-44::q0078 | conv-44 | 4 | 4 | +0 | What did Audrey and her friends stumble across during a hike a few years back, as mentioned on June 26, 2023? |
| conv-44::q0079 | conv-44 | 4 | 4 | +0 | What is Audrey's favorite recipe that she shares with Andrew on 3 July, 2023? |
| conv-44::q0080 | conv-44 | 4 | 4 | +0 | What dish is one of Audrey's favorite dishes that includes garlic and is shared with Andrew on 3 July, 2023? |
| conv-48::q0000 | conv-48 | 4 | 4 | +0 | What kind of project was Jolene working on in the beginning of January 2023? |
| conv-48::q0002 | conv-48 | 4 | 4 | +0 | When did Deborah`s mother pass away? |
| conv-48::q0003 | conv-48 | 4 | 4 | +0 | When did Jolene`s mother pass away? |
| conv-48::q0004 | conv-48 | 4 | 4 | +0 | When did Jolene's mom gift her a pendant? |
| conv-48::q0005 | conv-48 | 4 | 4 | +0 | In what country did Jolene's mother buy her the pendant? |
| conv-48::q0006 | conv-48 | 4 | 4 | +0 | What symbolic gifts do Deborah and Jolene have from their mothers? |
| conv-48::q0007 | conv-48 | 4 | 4 | +0 | Which country were Jolene and her mother visiting in 2010? |
| conv-48::q0009 | conv-48 | 4 | 4 | +0 | When did Deborah's father pass away? |
| conv-48::q0010 | conv-48 | 4 | 4 | +0 | When was Deborah's parents' wedding? |
| conv-48::q0011 | conv-48 | 4 | 4 | +0 | Is Deborah married? |
| conv-48::q0012 | conv-48 | 4 | 4 | +0 | When did Deborah receive an appreciation letter from her community? |
| conv-48::q0016 | conv-48 | 4 | 4 | +0 | What are the names of Jolene's snakes? |
| conv-48::q0017 | conv-48 | 4 | 4 | +0 | When did Jolene buy her pet Seraphim? |
| conv-48::q0018 | conv-48 | 4 | 4 | +0 | In what country did Jolene buy snake Seraphim? |
| conv-48::q0020 | conv-48 | 2 | 2 | +0 | Which games have Jolene and her partner played together? |
| conv-48::q0021 | conv-48 | 4 | 4 | +0 | When do Jolene and her partner plan to complete the game "Walking Dead"? |
| conv-48::q0022 | conv-48 | 4 | 4 | +0 | When did Deborah meet Anna? |
| conv-48::q0026 | conv-48 | 4 | 4 | +0 | Which book did Jolene read in January 2023? |
| conv-48::q0027 | conv-48 | 4 | 4 | +0 | When was Jolene in Bogota? |
| conv-48::q0033 | conv-48 | 4 | 4 | +0 | How long have Jolene and her partner been together? |
| conv-48::q0042 | conv-48 | 4 | 4 | +0 | What music pieces does Deborah listen to during her yoga practice? |
| conv-48::q0049 | conv-48 | 4 | 4 | +0 | How long has Jolene been doing yoga and meditation? |
| conv-48::q0058 | conv-48 | 4 | 4 | +0 | What games does Jolene recommend for Deborah? |
| conv-48::q0059 | conv-48 | 4 | 4 | +0 | What do Deborah and her husband do together? |
| conv-48::q0062 | conv-48 | 4 | 4 | +0 | Where did Deborah get her cats? |
| conv-48::q0063 | conv-48 | 4 | 4 | +0 | How old are Deborah's cats? |
| conv-48::q0064 | conv-48 | 4 | 4 | +0 | Does Deborah like cats? |
| conv-48::q0067 | conv-48 | 4 | 4 | +0 | What was Jolene doing with her partner in Rio de Janeiro? |
| conv-48::q0069 | conv-48 | 4 | 4 | +0 | Have Deborah and Jolene been to Rio de Janeiro? |
| conv-48::q0072 | conv-48 | 4 | 4 | +0 | When did Jolene's parents give her first console? |
| conv-48::q0074 | conv-48 | 4 | 4 | +0 | What do Deborah and Jolene plan to try when they meet in a new cafe? |
| conv-48::q0089 | conv-48 | 4 | 4 | +0 | What are the names of Jolene's snakes? |
| conv-48::q0091 | conv-48 | 4 | 4 | +0 | What music pieces does Deborah listen to during her yoga practice? |
| conv-48::q0092 | conv-48 | 4 | 4 | +0 | What games does Jolene recommend for Deborah? |
| conv-48::q0094 | conv-48 | 4 | 4 | +0 | Where did Deborah get her cats? |
| conv-48::q0095 | conv-48 | 4 | 4 | +0 | How old are Deborah's cats? |
| conv-48::q0096 | conv-48 | 4 | 4 | +0 | What was Jolene doing with her partner in Rio de Janeiro? |
| conv-48::q0097 | conv-48 | 4 | 4 | +0 | Have Deborah and Jolene been to Rio de Janeiro? |
| conv-48::q0098 | conv-48 | 4 | 4 | +0 | When did Jolene's parents give her first console? |
| conv-48::q0100 | conv-48 | 4 | 4 | +0 | What project did Jolene finish last week before 23 January, 2023? |
| conv-48::q0101 | conv-48 | 4 | 4 | +0 | When did Jolene buy her pet snake? |
| conv-48::q0102 | conv-48 | 4 | 4 | +0 | What project was Jolene working on as of 1 February, 2023? |
| conv-48::q0103 | conv-48 | 4 | 4 | +0 | Where did Deborah meet her new neighbor Anna? |
| conv-48::q0104 | conv-48 | 4 | 4 | +0 | What activity did Jolene and her partner plan to do together instead of resuming yoga? |
| conv-48::q0105 | conv-48 | 4 | 4 | +0 | What milestone did Jolene achieve recently on 4 February, 2023? |
| conv-48::q0106 | conv-48 | 4 | 4 | +0 | What is Jolene's favorite book which she mentioned on 4 February, 2023? |
| conv-48::q0107 | conv-48 | 4 | 4 | +0 | What does Deborah bring with her whenever she comes to reflect on her mom? |
| conv-48::q0109 | conv-48 | 4 | 4 | +0 | What cool stuff did Jolene accomplish at the retreat on 9 February, 2023? |
| conv-48::q0110 | conv-48 | 4 | 4 | +0 | What idea did Jolene have to help underprivileged kids learn about STEM subjects on 9 February, 2023? |
| conv-44::q0019 | conv-44 | 1 | 0 | -1 | What is an indoor activity that Andrew would enjoy doing while make his dog happy? |
| conv-48::q0019 | conv-48 | 1 | 0 | -1 | How many times has Jolene been to France? |
| conv-48::q0025 | conv-48 | 4 | 3 | -1 | What are Jolene's favorite books? |
| conv-48::q0090 | conv-48 | 4 | 3 | -1 | What are Jolene's favorite books? |
| conv-48::q0013 | conv-48 | 4 | 2 | -2 | What places give Deborah peace? |

## Interpretation rule

This frozen Test cannot be used to repair this candidate. Any later modification requires a new held-out split or dataset.
