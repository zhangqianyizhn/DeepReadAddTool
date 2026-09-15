# Qasper canonical-text autonomous single tool: frozen Test 120

## Protocol

- Candidate code, policy, canonical inventory, test split, Student, and Judge were frozen after dev passed.
- Test papers are disjoint from train and dev papers.
- No Analyzer or Repair Agent is called in this stage.
- Test is evaluated once; results are not development feedback.
- Candidate SHA-256: `4022e3f6fcaeb1f1f4a3977a1f04a64117c3c8a50f2965866c2f47c524bcba86`

## Results

| Arm | Normalized accuracy | Mean score (0-4) | Input tokens/q | Output tokens/q | Latency/q | Recall |
|---|---:|---:|---:|---:|---:|---:|
| Baseline | 82.08% | 3.283 | 77341 | 2645 | 29.1s | 92.46% |
| Frozen autonomous tool | 81.25% | 3.250 | 69047 | 2287 | 21.3s | 89.46% |

Paired: **8 wins / 104 ties / 8 losses**, net score **-4**.
Generated-tool use: **139 calls across 120/120 questions**.
Accuracy change: **-0.83%**.
Input-token change: **-10.72%**.
Output-token change: **-13.52%**.
Latency change: **-26.90%**.
Recall change: **-3.00%**.

## Per-question changes

| question_id | paper_id | Baseline | Tool | Delta | Question |
|---|---|---:|---:|---:|---|
| a381ba83a08148ce0324b48b8ff35128e66f580a | 1704.05907 | 0 | 2 | +2 | Based on the paper "End-to-End Multi-View Networks for Text Classification", what models did they compare to? |
| 569ad21441e99ae782d325d5f5e1ac19e08d5e76 | 1710.07395 | 2 | 4 | +2 | Based on the paper "Detecting Online Hate Speech Using Context Aware Models", What context do they use? |
| 1d739bb8e5d887fdfd1f4b6e39c57695c042fa25 | 1710.07395 | 2 | 4 | +2 | Based on the paper "Detecting Online Hate Speech Using Context Aware Models", What architecture has the neural network? |
| 15a1df59ed20aa415a4daf0acb256747f6766f77 | 1911.01188 | 0 | 2 | +2 | Based on the paper "Analysing Coreference in Transformer Outputs", Which coreference phenomena are analyzed? |
| 73abb173a3cc973ab229511cf53b426865a2738b | 1606.05286 | 2 | 4 | +2 | Based on the paper "Spectral decomposition method of dialog state tracking via collective matrix factorization", What state-of-the-art models are compared against? |
| b3bd217287b8c765b0d461dc283afec779dbf039 | 1808.04614 | 0 | 1 | +1 | Based on the paper "Explaining Queries over Web Tables to Non-Experts", Which query explanation method was preffered by the users in terms of correctness? |
| dd8f72cb3c0961b5ca1413697a00529ba60571fe | 1706.04815 | 3 | 4 | +1 | Based on the paper "S-Net: From Answer Extraction to Answer Generation for Machine Reading Comprehension", Why MS-MARCO is different from SQuAD? |
| db9021ddd4593f6fadf172710468e2fdcea99674 | 1910.11471 | 0 | 1 | +1 | Based on the paper "Machine Translation from Natural Language to Code using Long-Short Term Memory", What additional techniques are incorporated? |
| a7f07ae48eed084c3144214228f4ecb72bc0a0e3 | 1909.00997 | 2 | 2 | +0 | Based on the paper "Data Interpretation over Plots", What models other than SAN-VOES are trained on new PlotQA dataset? |
| 4e379d6d5f87554fabf6f7f7b6ed92d2025e7280 | 1901.03860 | 4 | 4 | +0 | Based on the paper "Prototypical Metric Transfer Learning for Continuous Speech Keyword Spotting With Limited Training Data", What problem do they apply transfer learning to? |
| 518d0847b02b4f23a8f441faa38b935c9b892e1e | 1901.03860 | 4 | 4 | +0 | Based on the paper "Prototypical Metric Transfer Learning for Continuous Speech Keyword Spotting With Limited Training Data", What are the baselines? |
| 8112d18681e266426cf7432ac4928b87f5ce8311 | 1901.03860 | 4 | 4 | +0 | Based on the paper "Prototypical Metric Transfer Learning for Continuous Speech Keyword Spotting With Limited Training Data", What languages are considered? |
| ba61ed892b4f7930430389e80a0c8e3b701c8e5d | 1910.11768 | 4 | 4 | +0 | Based on the paper "Exploring Multilingual Syntactic Sentence Representations", Which evaluation metrics do they use for language modelling? |
| 6a566095e25cbb56330456d7a1f3471693817712 | 1910.11768 | 4 | 4 | +0 | Based on the paper "Exploring Multilingual Syntactic Sentence Representations", Do they do quantitative quality analysis of learned embeddings? |
| 56c6ff65c64ca85951fdea54d6b096f28393c128 | 1910.11768 | 0 | 0 | +0 | Based on the paper "Exploring Multilingual Syntactic Sentence Representations", Do they evaluate on downstream tasks? |
| 356e462f7966e30665a387ed7a9ad2e830479da6 | 1910.11768 | 4 | 4 | +0 | Based on the paper "Exploring Multilingual Syntactic Sentence Representations", Which corpus do they use? |
| 04cab3325e20c61f19846674bf9a2c46ea60c449 | 1912.01679 | 4 | 4 | +0 | Based on the paper "Deep Contextualized Acoustic Representations For Semi-Supervised Speech Recognition", What are baseline models on WSJ eval92 and LibriSpeech test-clean? |
| e8647f9dc0986048694c34ab9ce763b3167c3deb | 1808.04614 | 0 | 0 | +0 | Based on the paper "Explaining Queries over Web Tables to Non-Experts", Do they conduct a user study where they show an NL interface with and without their explanation? |
| a2103e7fe613549a9db5e65008f33cf2ee0403bd | 1708.05873 | 4 | 4 | +0 | Based on the paper "What Drives the International Development Agenda? An NLP Analysis of the United Nations General Debate 1970-2016", What are the country-specific drivers of international development rhetoric? |
| 13b36644357870008d70e5601f394ec3c6c07048 | 1708.05873 | 0 | 0 | +0 | Based on the paper "What Drives the International Development Agenda? An NLP Analysis of the United Nations General Debate 1970-2016", Is the dataset multilingual? |
| e4a19b91b57c006a9086ae07f2d6d6471a8cf0ce | 1708.05873 | 4 | 4 | +0 | Based on the paper "What Drives the International Development Agenda? An NLP Analysis of the United Nations General Debate 1970-2016", How are the main international development topics that states raise identified? |
| 7835d8f578386834c02e2c9aba78a345059d56ca | 2001.06785 | 0 | 0 | +0 | Based on the paper "From Speech-to-Speech Translation to Automatic Dubbing", Is the model evaluated against a baseline? |
| 32e78ca99ba8b8423d4b21c54cd5309cb92191fc | 2001.06785 | 4 | 4 | +0 | Based on the paper "From Speech-to-Speech Translation to Automatic Dubbing", How many people are employed for the subjective evaluation? |
| 16646ee77975fed372b76ce639e2664ae2105dcf | 2002.06053 | 4 | 4 | +0 | Based on the paper "Exploring Chemical Space using Natural Language Processing Methodologies for Drug Discovery", Is there any concrete example in the paper that shows that this approach had huge impact on drug discovery? |
| 5d6cc65b73f428ea2a499bcf91995ef5441f63d4 | 1911.03350 | 4 | 4 | +0 | Based on the paper "Ask to Learn: A Study on Curiosity-driven Question Generation", How they evaluate quality of generated output? |
| 03b939ad70593f6475c56e9be73ba409d33faa62 | 1604.00125 | 4 | 4 | +0 | Based on the paper "AttSum: Joint Learning of Focusing and Summarization with Neural Attention", What models do they compare to? |
| a379c380ac9f67f824506951444c873713405eed | 1911.08962 | 0 | 0 | +0 | Based on the paper "CAIL2019-SCM: A Dataset of Similar Case Matching in Legal Domain", What are the baselines? |
| 439af1232a012fc4d94ef2ffe305dd405bee3888 | 1910.06061 | 4 | 4 | +0 | Based on the paper "Feature-Dependent Confusion Matrices for Low-Resource NER Labeling with Noisy Labels", What is baseline used? |
| b6a6bdca6dee70f8fe6dd1cfe3bb2c5ff03b1605 | 1910.06061 | 4 | 4 | +0 | Based on the paper "Feature-Dependent Confusion Matrices for Low-Resource NER Labeling with Noisy Labels", Did they evaluate against baseline? |
| 8951fde01b1643fcb4b91e51f84e074ce3b69743 | 1910.06061 | 4 | 4 | +0 | Based on the paper "Feature-Dependent Confusion Matrices for Low-Resource NER Labeling with Noisy Labels", How they evaluate their approach? |
| c348a8c06e20d5dee07443e962b763073f490079 | 1706.04815 | 4 | 4 | +0 | Based on the paper "S-Net: From Answer Extraction to Answer Generation for Machine Reading Comprehension", What two components are included in their proposed framework? |
| 0300cf768996849cab7463d929afcb0b09c9cf2a | 1706.04815 | 4 | 4 | +0 | Based on the paper "S-Net: From Answer Extraction to Answer Generation for Machine Reading Comprehension", Which framework they propose in this paper? |
| 864b5c1fe8c744f80a55e87421b29d6485b7efd0 | 1810.01570 | 4 | 4 | +0 | Based on the paper "A Deep Learning Architecture for De-identification of Patient Notes: Implementation and Evaluation", What evaluation metrics do they use? |
| 0a050658d09f3c6e21e9ab828dc18e59b147cf7c | 1810.01570 | 4 | 4 | +0 | Based on the paper "A Deep Learning Architecture for De-identification of Patient Notes: Implementation and Evaluation", Do they use BERT? |
| fd80a7162fde83077ed82ae41d521d774f74340a | 1810.01570 | 4 | 4 | +0 | Based on the paper "A Deep Learning Architecture for De-identification of Patient Notes: Implementation and Evaluation", What is their baseline? |
| 4d4739682d540878a94d8227412e9e1ec1bb3d39 | 1810.01570 | 4 | 4 | +0 | Based on the paper "A Deep Learning Architecture for De-identification of Patient Notes: Implementation and Evaluation", Which two datasets is the system tested on? |
| 2cfcc5864a30259fd35f1cc035fab956802c1c5b | 1906.09777 | 4 | 4 | +0 | Based on the paper "A Tensorized Transformer for Language Modeling", What datasets or tasks do they conduct experiments on? |
| 7f452eb145d486c15ac4d1107fc914e48ebba60f | 1912.06670 | 4 | 4 | +0 | Based on the paper "Common Voice: A Massively-Multilingual Speech Corpus", What crowdsourcing platform is used for data collection and data validation? |
| bb71a638668a21c2d446b44cbf51676c839658f7 | 1912.06670 | 4 | 4 | +0 | Based on the paper "Common Voice: A Massively-Multilingual Speech Corpus", How is validation of the data performed? |
| 5fa464a158dc8abf7cef8ca7d42a7080670c1edd | 1912.06670 | 4 | 4 | +0 | Based on the paper "Common Voice: A Massively-Multilingual Speech Corpus", Is audio data per language balanced in dataset? |
| 8d258899e36326183899ebc67aeb4188a86f682c | 1606.08140 | 4 | 4 | +0 | Based on the paper "STransE: a novel embedding model of entities and relationships in knowledge bases", What scoring function does the model use to score triples? |
| 955ca31999309685c1daa5cb03867971ca99ec52 | 1606.08140 | 4 | 4 | +0 | Based on the paper "STransE: a novel embedding model of entities and relationships in knowledge bases", What datasets are used to evaluate the model? |
| 524abe0ab77db168d5b2f0b68dba0982ac5c1d8e | 1901.00570 | 4 | 4 | +0 | Based on the paper "Event detection in Twitter: A keyword volume approach", Do the authors suggest any future extensions to this work? |
| 858c51842fc3c1f3e6d2d7d853c94f6de27afade | 1901.00570 | 0 | 0 | +0 | Based on the paper "Event detection in Twitter: A keyword volume approach", Which of the classifiers showed the best performance? |
| 7c9c73508da628d58aaadb258f3a9d4cc2a8a9b3 | 1901.00570 | 4 | 4 | +0 | Based on the paper "Event detection in Twitter: A keyword volume approach", Were any other word similar metrics, besides Jaccard metric, tested? |
| 7b2bf0c1a24a2aa01d49f3c7e1bdc7401162c116 | 1901.00570 | 4 | 4 | +0 | Based on the paper "Event detection in Twitter: A keyword volume approach", How are the keywords associated with events such as protests selected? |
| e98d331faacd50f8ec588d2466b5a85da1f37e6f | 1907.00455 | 4 | 4 | +0 | Based on the paper "Multiplicative Models for Recurrent Language Modeling", Do they compare results against state-of-the-art language models? |
| f319f2c3f9339b0ce47478f5aa0c32da387a156e | 1907.00455 | 4 | 4 | +0 | Based on the paper "Multiplicative Models for Recurrent Language Modeling", Which dataset do they train their models on? |
| 95c7b27d192ab0edcdf203a74ce24f4a9a814e6c | 2003.09971 | 4 | 4 | +0 | Based on the paper "A Better Variant of Self-Critical Sequence Training", What baseline function is used in REINFORCE algorithm? |
| e196e2ce72eb8b2d50732c26e9bf346df6643f69 | 1809.09795 | 4 | 4 | +0 | Based on the paper "Deep contextualized word representations for detecting sarcasm and irony", Do they evaluate only on English? |
| 46570c8faaeefecc8232cfc2faab0005faaba35f | 1809.09795 | 4 | 4 | +0 | Based on the paper "Deep contextualized word representations for detecting sarcasm and irony", What are the 7 different datasets? |
| 982d375378238d0adbc9a4c987d633ed16b7f98f | 1809.09795 | 4 | 4 | +0 | Based on the paper "Deep contextualized word representations for detecting sarcasm and irony", What are the three different sources of data? |
| bbdb2942dc6de3d384e3a1b705af996a5341031b | 1809.09795 | 4 | 4 | +0 | Based on the paper "Deep contextualized word representations for detecting sarcasm and irony", What type of model are the ELMo representations used in? |
| 4ec538e114356f72ef82f001549accefaf85e99c | 1809.09795 | 4 | 4 | +0 | Based on the paper "Deep contextualized word representations for detecting sarcasm and irony", Which morphosyntactic features are thought to indicate irony or sarcasm? |
| a458c649a793588911cef4c421f95117d0b9c472 | 1902.07285 | 4 | 4 | +0 | Based on the paper "Towards a Robust Deep Neural Network in Text Domain A Survey", Which strategies show the most promise in deterring these attacks? |
| 4f0f446bf4518af7f539f6283145135192d5c00b | 1610.08597 | 4 | 4 | +0 | Based on the paper "Word Embeddings to Enhance Twitter Gang Member Profile Identification", Which supervised learning algorithms are used in the experiments? |
| 663b36f99ad2422f4d3a8c6398ebf55ceab7770d | 1610.08597 | 4 | 4 | +0 | Based on the paper "Word Embeddings to Enhance Twitter Gang Member Profile Identification", How in YouTube content translated into a vector format? |
| be595b2017545b0359db6abf4914a155bdd10d23 | 1610.08597 | 1 | 1 | +0 | Based on the paper "Word Embeddings to Enhance Twitter Gang Member Profile Identification", How is the ground truth of gang membership established in this dataset? |
| edb068df4ffbd73b379590762125990fcd317862 | 1704.05907 | 4 | 4 | +0 | Based on the paper "End-to-End Multi-View Networks for Text Classification", which benchmark tasks did they experiment on? |
| 1f1a9f2dd8c4c10b671cb8affe56e181948e229e | 1907.12108 | 4 | 4 | +0 | Based on the paper "CAiRE: An End-to-End Empathetic Chatbot", What pretrained LM is used? |
| 9776156fc93daa36f4613df591e2b49827d25ad2 | 1803.09230 | 0 | 0 | +0 | Based on the paper "Pay More Attention - Neural Architectures for Question-Answering", By how much, the proposed method improves BiDAF and DCN on SQuAD dataset? |
| 9257c578ee19a7d93e2fba866be7b0bf1142c393 | 1810.10254 | 4 | 4 | +0 | Based on the paper "Learn to Code-Switch: Data Augmentation using Copy Mechanism on Language Modeling", Did they use other evaluation metrics? |
| 657edbf39c500b2446edb9cca18de2912c628b7d | 1810.10254 | 0 | 0 | +0 | Based on the paper "Learn to Code-Switch: Data Augmentation using Copy Mechanism on Language Modeling", What was their perplexity score? |
| 235c156d9c2adc895c9113f53c60f2dd8df45834 | 1810.10254 | 4 | 4 | +0 | Based on the paper "Learn to Code-Switch: Data Augmentation using Copy Mechanism on Language Modeling", What languages are explored in this paper? |
| dd2046f5481f11b7639a230e8ca92904da75feed | 1710.07395 | 4 | 4 | +0 | Based on the paper "Detecting Online Hate Speech Using Context Aware Models", How do they combine the models? |
| 47e6c3e6fcc9be8ca2437f41a4fef58ef4c02579 | 1710.07395 | 4 | 4 | +0 | Based on the paper "Detecting Online Hate Speech Using Context Aware Models", What is their baseline? |
| 90741b227b25c42e0b81a08c279b94598a25119d | 1710.07395 | 4 | 4 | +0 | Based on the paper "Detecting Online Hate Speech Using Context Aware Models", What is their definition of hate speech? |
| abad9beb7295d809d7e5e1407cbf673c9ffffd19 | 1907.01413 | 4 | 4 | +0 | Based on the paper "Speaker-independent classification of phonetic segments from raw ultrasound in child speech", Do they propose any further additions that could be made to improve generalisation to unseen speakers? |
| 265c9b733e4dfffb76acfbade4c0c9b14d3ccde1 | 1907.01413 | 4 | 4 | +0 | Based on the paper "Speaker-independent classification of phonetic segments from raw ultrasound in child speech", What are the characteristics of the dataset? |
| 0f928732f226185c76ad5960402e9342c0619310 | 1907.01413 | 4 | 4 | +0 | Based on the paper "Speaker-independent classification of phonetic segments from raw ultrasound in child speech", What type of models are used for classification? |
| 11c5b12e675cfd8d1113724f019d8476275bd700 | 1907.01413 | 0 | 0 | +0 | Based on the paper "Speaker-independent classification of phonetic segments from raw ultrasound in child speech", Do they compare to previous work? |
| d24acc567ebaec1efee52826b7eaadddc0a89e8b | 1907.01413 | 4 | 4 | +0 | Based on the paper "Speaker-independent classification of phonetic segments from raw ultrasound in child speech", How many instances does their dataset have? |
| 2d62a75af409835e4c123a615b06235a352a67fe | 1907.01413 | 4 | 4 | +0 | Based on the paper "Speaker-independent classification of phonetic segments from raw ultrasound in child speech", What model do they use to classify phonetic segments?  |
| fffbd6cafef96eeeee2f9fa5d8ab2b325ec528e6 | 1907.01413 | 4 | 4 | +0 | Based on the paper "Speaker-independent classification of phonetic segments from raw ultrasound in child speech", How many speakers do they have in the dataset? |
| bb570d4a1b814f508a07e74baac735bf6ca0f040 | 1807.05154 | 4 | 4 | +0 | Based on the paper "Deep Enhanced Representation for Implicit Discourse Relation Recognition", Why does their model do better than prior models? |
| 96c20af8bbef435d0d534d10c42ae15ff2f926f8 | 1911.01188 | 4 | 4 | +0 | Based on the paper "Analysing Coreference in Transformer Outputs", What translationese effects are seen in the analysis? |
| 9544cc0244db480217ce9174aa13f1bf09ba0d94 | 1911.01188 | 4 | 4 | +0 | Based on the paper "Analysing Coreference in Transformer Outputs", What languages are seen in the news and TED datasets? |
| 3758669426e8fb55a4102564cf05f2864275041b | 1911.01188 | 4 | 4 | +0 | Based on the paper "Analysing Coreference in Transformer Outputs", How are the (possibly incorrect) coreference chains in the MT outputs annotated? |
| 1ebd6f703458eb6690421398c79abf3fc114148f | 1911.01188 | 4 | 4 | +0 | Based on the paper "Analysing Coreference in Transformer Outputs", Which three neural machine translation systems are analyzed? |
| d79d897f94e666d5a6fcda3b0c7e807c8fad109e | 1910.02789 | 4 | 4 | +0 | Based on the paper "Natural Language State Representation for Reinforcement Learning", What result from experiments suggest that natural language based agents are more robust? |
| 8e857e44e4233193c7b2d538e520d37be3ae1552 | 1910.02789 | 4 | 4 | +0 | Based on the paper "Natural Language State Representation for Reinforcement Learning", What experiments authors perform? |
| 084fb7c80a24b341093d4bf968120e3aff56f693 | 1910.02789 | 4 | 4 | +0 | Based on the paper "Natural Language State Representation for Reinforcement Learning", How is state to learn and complete tasks represented via natural language? |
| dc5ff2adbe1a504122e3800c9ca1d348de391c94 | 1809.02731 | 4 | 4 | +0 | Based on the paper "Exploiting Invertible Decoders for Unsupervised Sentence Representation Learning", How do they evaluate the sentence representations? |
| 04b43deab0fd753e3419ed8741c10f652b893f02 | 1809.02731 | 4 | 4 | +0 | Based on the paper "Exploiting Invertible Decoders for Unsupervised Sentence Representation Learning", What are the two decoding functions? |
| 37c7c62c9216d6cf3d0858cf1deab6db4b815384 | 1704.02385 | 4 | 4 | +0 | Based on the paper "A Trolling Hierarchy in Social Media and A Conditional Random Field For Trolling Detection", how was annotation done? |
| 539eb559744641e6a4aefe267cbc4c79e2bcceae | 1704.02385 | 4 | 4 | +0 | Based on the paper "A Trolling Hierarchy in Social Media and A Conditional Random Field For Trolling Detection", what is the source of the new dataset? |
| 8ea4bd4c1d8a466da386d16e4844ea932c44a412 | 1910.11471 | 4 | 4 | +0 | Based on the paper "Machine Translation from Natural Language to Code using Long-Short Term Memory", What dataset do they use? |
| 92240eeab107a4f636705b88f00cefc4f0782846 | 1910.11471 | 4 | 4 | +0 | Based on the paper "Machine Translation from Natural Language to Code using Long-Short Term Memory", Do they compare to other models? |
| 4196d329061f5a9d147e1e77aeed6a6bd9b35d18 | 1910.11471 | 4 | 4 | +0 | Based on the paper "Machine Translation from Natural Language to Code using Long-Short Term Memory", What is the architecture of the system? |
| 321429282557e79061fe2fe02a9467f3d0118cdd | 1910.11471 | 4 | 4 | +0 | Based on the paper "Machine Translation from Natural Language to Code using Long-Short Term Memory", What additional techniques could be incorporated to further improve accuracy? |
| 891cab2e41d6ba962778bda297592c916b432226 | 1910.11471 | 4 | 4 | +0 | Based on the paper "Machine Translation from Natural Language to Code using Long-Short Term Memory", What programming language is target language? |
| 1eeabfde99594b8d9c6a007f50b97f7f527b0a17 | 1910.11471 | 4 | 4 | +0 | Based on the paper "Machine Translation from Natural Language to Code using Long-Short Term Memory", What dataset is used to measure accuracy? |
| b42323d60827ecf0d9e478c9a31f90940cfae975 | 1705.03261 | 4 | 4 | +0 | Based on the paper "Drug-drug Interaction Extraction via Recurrent Neural Network with Multiple Attention Layers", How big is the evaluated dataset? |
| 1a69696034f70fb76cd7bb30494b2f5ab97e134d | 1705.03261 | 0 | 0 | +0 | Based on the paper "Drug-drug Interaction Extraction via Recurrent Neural Network with Multiple Attention Layers", By how much does their model outperform existing methods? |
| 1ba28338d3f993674a19d2ee2ec35447e361505b | 1705.03261 | 4 | 4 | +0 | Based on the paper "Drug-drug Interaction Extraction via Recurrent Neural Network with Multiple Attention Layers", What are the existing methods mentioned in the paper? |
| 046ff04d1018447b22e00acb125125cae5a23fb7 | 1911.11933 | 4 | 4 | +0 | Based on the paper "Simultaneous Neural Machine Translation using Connectionist Temporal Classification", Which dataset do they use? |
| 5a06f11aa75a8affde3d595c40fb03e06769e368 | 1911.11933 | 4 | 4 | +0 | Based on the paper "Simultaneous Neural Machine Translation using Connectionist Temporal Classification", Do they trim the search space of possible output sequences? |
| ffbd6f583692db66b719a846ba2b7f6474df481a | 1911.11933 | 4 | 4 | +0 | Based on the paper "Simultaneous Neural Machine Translation using Connectionist Temporal Classification", Which model architecture do they use to build a model? |
| 74fe054f5243c8593ddd2c0628f91657246b7dfa | 1911.11933 | 0 | 0 | +0 | Based on the paper "Simultaneous Neural Machine Translation using Connectionist Temporal Classification", Do they compare simultaneous translation performance to regular machine translation? |
| cc2b98b46497c71e955e844fb36e9ef6e2784640 | 1911.11933 | 4 | 4 | +0 | Based on the paper "Simultaneous Neural Machine Translation using Connectionist Temporal Classification", Which metrics do they use to evaluate simultaneous translation? |
| a4e66e842be1438e5cd8d7cb2a2c589f494aee27 | 1910.11769 | 0 | 0 | +0 | Based on the paper "DENS: A Dataset for Multi-class Emotion Analysis", Which tested technique was the worst performer? |
| cb78e280e3340b786e81636431834b75824568c3 | 1910.11769 | 4 | 4 | +0 | Based on the paper "DENS: A Dataset for Multi-class Emotion Analysis", How many emotions do they look at? |
| 2941874356e98eb2832ba22eae9cb08ec8ce0308 | 1910.11769 | 4 | 4 | +0 | Based on the paper "DENS: A Dataset for Multi-class Emotion Analysis", What are the baseline benchmarks? |
| 4e50e9965059899d15d3c3a0c0a2d73e0c5802a0 | 1910.11769 | 4 | 4 | +0 | Based on the paper "DENS: A Dataset for Multi-class Emotion Analysis", What is the size of this dataset? |
| 67d8e50ddcc870db71c94ad0ad7f8a59a6c67ca6 | 1910.11769 | 4 | 4 | +0 | Based on the paper "DENS: A Dataset for Multi-class Emotion Analysis", How many annotators were there? |
| d5256d684b5f1b1ec648d996c358e66fe51f4904 | 1808.04314 | 4 | 4 | +0 | Based on the paper "Comparing morphological complexity of Spanish, Otomi and Nahuatl", what is the practical application for this paper? |
| 3efc0981e7f959d916aa8bb32ab1c347b8474ff8 | 1804.00520 | 4 | 4 | +0 | Based on the paper "NIHRIO at SemEval-2018 Task 3: A Simple and Accurate Neural Network Model for Irony Detection in Twitter", What type of lexical, syntactic, semantic and polarity features are used? |
| cfb5ab893ed77f9df7eeb4940b6bacdef5acccea | 1909.05360 | 4 | 4 | +0 | Based on the paper "Joint Event and Temporal Relation Extraction with Shared Representations and Structured Prediction", Is this the first paper to propose a joint model for event and temporal relation extraction? |
| a5abd4dd91e6f2855e9098bd6ae1481c0fdb0d4a | 1909.05360 | 4 | 4 | +0 | Based on the paper "Joint Event and Temporal Relation Extraction with Shared Representations and Structured Prediction", What datasets were used for this work? |
| d2473c039ab85f8e9e99066894658381ae852e16 | 1805.00460 | 4 | 4 | +0 | Based on the paper "Customized Image Narrative Generation via Interactive Visual Question Generation and Answering", What are the features of used to customize target user interaction?  |
| bd3ccb63fd8ce5575338d7332e96def7a3fabad6 | 1910.00912 | 2 | 2 | +0 | Based on the paper "Hierarchical Multi-Task Natural Language Understanding for Cross-domain Conversational AI: HERMIT NLU", Which publicly available NLU dataset is used? |
| 7c794fa0b2818d354ca666969107818a2ffdda0c | 1910.00912 | 4 | 4 | +0 | Based on the paper "Hierarchical Multi-Task Natural Language Understanding for Cross-domain Conversational AI: HERMIT NLU", What metrics other than entity tagging are compared? |
| e2a637f1d93e1ea9f29c96ff0fc6bc017209065b | 1808.04614 | 1 | 0 | -1 | Based on the paper "Explaining Queries over Web Tables to Non-Experts", How do they gather data for the query explanation problem? |
| 9a596bd3a1b504601d49c2bec92d1592d7635042 | 1705.03261 | 2 | 1 | -1 | Based on the paper "Drug-drug Interaction Extraction via Recurrent Neural Network with Multiple Attention Layers", What is the performance of their model? |
| 8c8a32592184c88f61fac1eef12c7d233dbec9dc | 2002.06053 | 3 | 1 | -2 | Based on the paper "Exploring Chemical Space using Natural Language Processing Methodologies for Drug Discovery", Are this models usually semi/supervised or unsupervised? |
| 0a8bc204a76041a25cee7e9f8e2af332a17da67a | 1911.03350 | 4 | 2 | -2 | Based on the paper "Ask to Learn: A Study on Curiosity-driven Question Generation", What automated metrics authors investigate? |
| bde6fa2057fa21b38a91eeb2bb6a3ae7fb3a2c62 | 1704.05907 | 2 | 0 | -2 | Based on the paper "End-to-End Multi-View Networks for Text Classification", what state of the accuracy did they obtain? |
| fa2ffc6b4b046e17bc41e199855c4941673e2caf | 1810.10254 | 4 | 2 | -2 | Based on the paper "Learn to Code-Switch: Data Augmentation using Copy Mechanism on Language Modeling", What parallel corpus did they use? |
| f8d32088d17b32b0c877d59965b35c4f51f0ceea | 1610.08597 | 4 | 1 | -3 | Based on the paper "Word Embeddings to Enhance Twitter Gang Member Profile Identification", Do the authors report on English datasets only? |
| a45edc04277a458911086752af4f17405501230f | 2002.06053 | 4 | 0 | -4 | Based on the paper "Exploring Chemical Space using Natural Language Processing Methodologies for Drug Discovery", Are datasets publicly available? |

## Interpretation rule

This is the final held-out result. Any future modification requires a new split or dataset; this test cannot be used to repair the candidate.
