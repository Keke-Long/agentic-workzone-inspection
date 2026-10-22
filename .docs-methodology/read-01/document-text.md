# workzone论文

- Document ID: 1e3KD9OhqH2JJFUhKSBKqXsOFD_YIzEOtp8wBPTfjZeQ
- Revision ID: ANLCKQlcFzVRsD-3bFFJPOdIo6syw1MACfSnsPUd58iVPbkVI6FvlIeH8jPxI4d4XI6gJr98w1COB2yDpWyDXanClcLv-py9HW6HsR8lHe0
- Selected tab: t.0
- Protected controls: 0
- Opaque controls: 0
- Authoritative dropdowns: 0

Protected-control annotations are preservation instructions. Do not insert their displayed placeholder text to recreate a native control.

## Tab 1 (t.0)

[P00001 | 1:77 | TITLE]
Automatic Agentic VLM Inspection of Work Zones Using Connected Vehicle Data

[P00002 | 77:78 | SUBTITLE]
⟦EMPTY PARAGRAPH⟧

[P00003 | 78:87 | HEADING_1]
Abstract

[P00004 | 87:1410 | NORMAL_TEXT]
Work-zone traffic control devices must be deployed and maintained in accordance with context-dependent requirements, yet field inspection is labor-intensive and difficult to conduct continuously. Connected vehicles can collect synchronized roadway imagery, LiDAR point clouds, and positioning data during routine travel, creating an opportunity to support recurring inspection without requiring a dedicated survey for every visit. The challenge is not only to detect objects, but also to determine which requirements apply to a given work-zone scene, identify which inspection questions are observable from the available data, coordinate specialized analysis tools, and preserve the evidence supporting each conclusion. This paper develops a structure-guided agentic workflow that connects work-zone manuals with multimodal connected-vehicle data. The manual structure guides regulatory retrieval, while an agent dynamically selects inspection tasks, plans tool calls, responds to intermediate results or failures, and assembles evidence-grounded inspection records. The workflow is evaluated on real work-zone traversals using human-established ground truth at the tool, inspection, and system levels. Quantitative results and the final inspection scope will be inserted after data auditing and experiments are completed.

[P00005 | 1410:1550 | NORMAL_TEXT]
Keywords: work-zone inspection; agentic AI; connected vehicles; multimodal sensing; retrieval-augmented generation; traffic control devices

[P00006 | 1550:1566 | HEADING_1]
1. Introduction

[P00007 | 1566:2350 | NORMAL_TEXT]
Work-zone safety is a persistent transportation challenge. Work zones were reported to account for more than 2% of all fatal crashes in the United States each year since 2016 [(Finley & Ullman, 2023)](https://rosap.ntl.bts.gov/view/dot/72451). The burden extends beyond fatal events: a work-zone crash occurred approximately every five minutes nationwide during 2015–2019 [(Qian et al., 2024)](https://rosap.ntl.bts.gov/view/dot/77512). Crashes also impose substantial economic losses. The average economic cost of a property-damage-only crash is estimated at $18,100 in 2024 dollars [(FHWA, 2025)](https://highways.fhwa.dot.gov/sites/fhwa.dot.gov/files/2025-10/CrashCostFactSheet_508_OCT2025.pdf). These safety and economic burdens motivate timely inspection of temporary traffic-control facilities. As work progresses and traffic arrangements change, agencies need to identify deficient, displaced, or obscured devices and refer potential problems for corrective action.

[P00008 | 2350:2351 | NORMAL_TEXT]
⟦EMPTY PARAGRAPH⟧

[P00009 | 2351:3056 | NORMAL_TEXT]
Conventional work-zone inspection relies on field visits and manual review of imagery and records. Staff time and travel requirements constrain how frequently geographically dispersed work zones can be inspected. Geotagged images collected by commercial trucks during routine travel can support repeated remote review of sign placement, lane configurations, maintenance closures, and pavement markings [(Overall et al., 2026)](https://doi.org/10.4236/jtts.2026.161006). This establishes a practical opportunity to use passing vehicles as an information source for inspection. Where instrumented vehicles also provide synchronized LiDAR and positioning data, their observations may support selected spatial measurements in addition to visual review.

[P00010 | 3056:3057 | NORMAL_TEXT]
⟦EMPTY PARAGRAPH⟧

[P00011 | 3057:3671 | NORMAL_TEXT]
Existing vehicle-based inspection systems have already automated data collection. Traffic-sign tracking, tilt and occlusion assessment, and geolocated reporting have been integrated into a monitoring workflow, with mobile LiDAR used to validate geometric estimates. This workflow converts roadway observations into actionable asset records for predefined sign-condition tasks [(Dwairi et al., 2026)](https://doi.org/10.1007/s41062-026-02676-0). In a demonstrated work-zone application, an AI experiment screened images for the presence of a work zone, while the assessment of traffic-control practices still relied on manual inspection [(Overall et al., 2026)](https://doi.org/10.4236/jtts.2026.161006).

[P00012 | 3671:3672 | NORMAL_TEXT]
⟦EMPTY PARAGRAPH⟧

[P00013 | 3672:4460 | NORMAL_TEXT]
Across engineering domains, there is a shared need to automate the assessment of whether designs, assets, and site conditions conform to applicable requirements. Automated compliance checking addresses this need by organizing regulatory requirements, information about the object under review, and specialized analysis tools into workflows that produce conformance judgments and review reports. Such workflows have been applied to BIM-based design review [(Peng & Liu, 2023)](https://doi.org/10.1038/s41598-023-34342-1), integrated construction compliance checking [(Beach et al., 2024)](https://doi.org/10.1016/j.aei.2023.102288), and building operation assessment [(Beach et al., 2025)](https://doi.org/10.1080/15623599.2024.2366727). LLMs have also been incorporated into BIM code checking [(Madireddy et al., 2025)](https://doi.org/10.3390/electronics14112146), adaptive design review [(Alnuzha & Bloch, 2026)](https://doi.org/10.36680/j.itcon.2026.038), and construction-site safety monitoring [(Chan et al., 2025)](https://doi.org/10.1016/j.autcon.2025.106305).

[P00014 | 4460:4461 | NORMAL_TEXT]
⟦EMPTY PARAGRAPH⟧

[P00015 | 4461:5211 | NORMAL_TEXT]
However, automated compliance checking remains underexplored in work-zone inspection using vehicle-collected data. The vehicle-based studies above do not demonstrate this capability, while the cross-domain systems address different objects, information structures, and inspection tasks. In a work zone, a requirement may depend on roadway type, speed, closure configuration, and work duration. The available observations may reveal a device without establishing its condition or its spacing relative to another device. Applying the checking paradigm therefore requires the system to associate the scene with the relevant requirement, obtain the evidence needed for that particular check, and recognize when the traversal cannot support a conclusion.

[P00016 | 5211:5212 | NORMAL_TEXT]
⟦EMPTY PARAGRAPH⟧

[P00017 | 5212:6064 | NORMAL_TEXT]
This study develops a structure-guided agentic workflow for that purpose. It links connected-vehicle imagery, LiDAR, and positioning data with temporary-traffic-control manuals and specialized analysis tools. Structure-guided retrieval-augmented generation (RAG) uses the manual's organization of conditions, typical configurations, device requirements, tables, and notes to narrow the retrieval scope and retain the context needed to interpret a requirement. The design addresses the possibility that a textually relevant passage is not applicable to the observed scene. An agent then selects inspection items, coordinates tool execution, and responds to intermediate evidence or failures. The output connects each inspection status with its regulatory source and observed evidence, including referral for human review when a judgment is unsupported.

[P00018 | 6064:6065 | NORMAL_TEXT]
⟦EMPTY PARAGRAPH⟧

[P00019 | 6065:6427 | NORMAL_TEXT]
The paper makes two contributions. First, it develops an agentic work-zone inspection workflow that combines multimodal vehicle data with structure-guided RAG to produce inspection reports grounded in traffic-control requirements and observed evidence. Second, it evaluates the workflow on real work-zone data to assess its accuracy and practical applicability.

[P00020 | 6427:6442 | HEADING_1]
2. Methodology

[P00021 | 6442:6462 | HEADING_2]
2.1 System Overview

[P00022 | 6462:6484 | NORMAL_TEXT]
画一个整体框架图，包含6个stage，这个

[P00023 | 6484:6522 | NORMAL_TEXT]
输入是车载lidar + camera，没有telematics data

[P00024 | 6522:6524 | NORMAL_TEXT]
[INLINE_OBJECT kix.bzv4j77118wr]

[P00025 | 6524:6565 | NORMAL_TEXT]
Fig 1 Structure of Agentic AI inspection

[P00026 | 6565:6566 | NORMAL_TEXT]
⟦EMPTY PARAGRAPH⟧

[P00027 | 6566:6567 | NORMAL_TEXT]
⟦EMPTY PARAGRAPH⟧

[P00028 | 6567:6568 | NORMAL_TEXT]
⟦EMPTY PARAGRAPH⟧

[P00029 | 6568:6591 | HEADING_1]
3. Experimental Design

[P00030 | 6591:6607 | HEADING_2]
3.1 Data Source

[P00031 | 6607:6726 | NORMAL_TEXT]
Data were collected at two work zones in Madison, Wisconsin, using our laboratory's Level 3 automated driving vehicle.

[P00032 | 6726:6785 | NORMAL_TEXT]
[Camera and LiDAR models and dataset details to be added.]

[P00033 | 6785:6806 | HEADING_2]
3.2 Compared Systems

[P00034 | 6806:7036 | NORMAL_TEXT]
Baseline 1 — Direct multimodal judgment: Available images and scene text are provided directly to a multimodal model, which produces an inspection judgment without external regulatory, perception, geometry, or localization tools.

[P00035 | 7036:7407 | NORMAL_TEXT]
Baseline 2 — Rule-based if–then workflow: Prespecified scene-profile conditions and inspection items trigger a fixed, human-authored tool chain. The workflow may read the same scene profile as the proposed approach, but the selected tools and their order are determined in advance. It does not replan in response to retrieval results, tool failures, or evidence quality.

[P00036 | 7407:7718 | NORMAL_TEXT]
Proposed — Agentic workflow: The agent receives the same inputs but determines applicable tasks and tool order dynamically. It may continue, switch, retry, narrow a task, stop, or request human review based on regulatory retrieval and intermediate tool outputs, while preserving a complete evidence trajectory.

[P00037 | 7718:7744 | HEADING_2]
3.3 Tool-Level Evaluation

[P00038 | 7744:8260 | NORMAL_TEXT]
Visual detection will be evaluated using precision, recall, F1, and/or mAP as appropriate to the selected model and annotation unit. Device-condition classification will use per-class precision, recall, and F1. Geometric measurement will use mean absolute error, root mean squared error, and valid-measurement rate. Structure-guided RAG will be evaluated through applicability retrieval, Recall@k for governing sources, final citation correctness, and correctness of extracted conditions and numerical requirements.

[P00039 | 8260:8292 | HEADING_2]
3.4 Inspection-Level Evaluation

[P00040 | 8292:8671 | NORMAL_TEXT]
For applicable and observable items, the study will report inspection-status accuracy, macro-F1, and item-specific performance. Not observable and requires human review will be evaluated as explicit system behaviors using coverage, selective accuracy, and unnecessary-review rate. This treatment prevents abstention from being counted automatically as either success or failure.

[P00041 | 8671:8709 | HEADING_2]
3.5 Agent and System-Level Evaluation

[P00042 | 8709:9205 | NORMAL_TEXT]
System evaluation will report inspection-item selection accuracy, tool selection accuracy, valid execution-plan rate, successful completion rate, evidence-field completeness, regulatory and observation traceability, execution time, and computational cost. Agent traces will also be categorized by whether they continued, switched tools, retried, narrowed the task, stopped, or requested review, allowing the claimed adaptive behavior to be measured rather than illustrated only through examples.

[P00043 | 9205:9237 | HEADING_2]
3.6 Human Evaluation of Reports

[P00044 | 9237:9547 | NORMAL_TEXT]
Reviewers with transportation-engineering knowledge will assess the correctness, clarity, evidentiary support, and practical review value of generated inspection records. The evaluation protocol, reviewer count, rating scale, adjudication procedure, and inter-rater reliability measure remain to be finalized.

[P00045 | 9547:9584 | HEADING_2]
3.7 Ablation and Diagnostic Analysis

[P00046 | 9584:10032 | NORMAL_TEXT]
Ablations will isolate the effects of manual structure guidance, dynamic planning, and access to selected sensing tools. Diagnostic analysis will separate errors in scene understanding, applicability determination, retrieval, object detection, condition assessment, geometry, tool selection, deterministic comparison, and evidence aggregation. The final ablation set will be limited to comparisons that directly support the two research questions.

[P00047 | 10032:10043 | HEADING_1]
4. Results

[P00048 | 10043:10174 | NORMAL_TEXT]
This section intentionally contains no assumed results. Tables and figures below define the outputs required from the experiments.

[P00049 | 10174:10213 | HEADING_2]
4.1 Structure-Guided Retrieval Results

[P00050 | 10213:10483 | NORMAL_TEXT]
Table 1 (to be completed): retrieval and requirement-extraction performance for unstructured retrieval and Structure-guided RAG. Include governing-source Recall@k, applicability accuracy, citation correctness, condition extraction, and numerical requirement extraction.

[P00051 | 10483:10506 | HEADING_2]
4.2 Tool-Level Results

[P00052 | 10506:10741 | NORMAL_TEXT]
Table 2 (to be completed): performance of visual detection and condition assessment by device class. Table 3 (to be completed): geometric measurement error and valid-measurement rate by range, device type, and sensing-quality stratum.

[P00053 | 10741:10775 | HEADING_2]
4.3 End-to-End Inspection Results

[P00054 | 10775:10986 | NORMAL_TEXT]
Table 4 (to be completed): item-level inspection accuracy, macro-F1, coverage, selective accuracy, and review rate for Direct multimodal judgment, Rule-based if–then workflow, and the proposed Agentic workflow.

[P00055 | 10986:11020 | HEADING_2]
4.4 Planning and Tool-Use Results

[P00056 | 11020:11200 | NORMAL_TEXT]
Table 5 (to be completed): inspection-item selection, tool selection, plan validity, completion, evidence completeness, traceability, runtime, cost, and observed adaptive actions.

[P00057 | 11200:11246 | HEADING_2]
4.5 Representative Cases and Failure Analysis

[P00058 | 11246:11608 | NORMAL_TEXT]
Figure 1 (to be developed): system overview. Figure 2 (to be developed): Structure-guided RAG and dynamic execution loop. Figure 3 (to be completed): representative end-to-end evidence trace. Figure 4 (to be completed): successful geometric inspection using synchronized image and point-cloud evidence. Table 6 (to be completed): failure taxonomy and frequency.

[P00059 | 11608:11623 | HEADING_1]
5. Conclusions

[P00060 | 11623:11976 | NORMAL_TEXT]
This study develops a structure-guided agentic workflow for converting connected-vehicle observations into traceable work-zone inspection records. The final conclusion will be written after experiments establish the reliability of the component tools, the value of dynamic orchestration, the supported inspection scope, and the principal failure modes.

[P00061 | 11976:11987 | HEADING_1]
References

[P00062 | 11987:12217 | NORMAL_TEXT]
Alnuzha, M., & Bloch, T. (2026). Integrating large language models and knowledge graphs for adaptive design review. Journal of Information Technology in Construction (ITcon), 31, 888–916. [https://doi.org/10.36680/j.itcon.2026.038](https://doi.org/10.36680/j.itcon.2026.038)

[P00063 | 12217:12518 | NORMAL_TEXT]
Beach, T., Yeung, J., Ghoroghi, A., & Rezgui, Y. (2025). Moving automated compliance checking to the operational phase of the building life-cycle: Analysis and feasibility study in the UK. International Journal of Construction Management, 25(7), 840–849. [https://doi.org/10.1080/15623599.2024.2366727](https://doi.org/10.1080/15623599.2024.2366727)

[P00064 | 12518:12801 | NORMAL_TEXT]
Beach, T., Yeung, J., Nisbet, N., & Rezgui, Y. (2024). Digital approaches to construction compliance checking: Validating the suitability of an ecosystem approach to compliance checking. Advanced Engineering Informatics, 59, Article 102288. [https://doi.org/10.1016/j.aei.2023.102288](https://doi.org/10.1016/j.aei.2023.102288)

[P00065 | 12801:13117 | NORMAL_TEXT]
Chan, C. F., Wong, K. Y., Guo, X., Cheng, J. C. P., Chan, J. P. C., Leung, P. H., & Tao, X. (2025). Context-aware vision-language model agent enriched with domain-specific ontology for construction site safety monitoring. Automation in Construction, 177, Article 106305. [https://doi.org/10.1016/j.autcon.2025.106305](https://doi.org/10.1016/j.autcon.2025.106305)

[P00066 | 13117:13343 | NORMAL_TEXT]
Dwairi, M., Manasreh, D., Melhem, M., & Nazzal, M. D. (2026). Automated traffic signs condition monitoring using machine vision. Innovative Infrastructure Solutions, 11, Article 325. [https://doi.org/10.1007/s41062-026-02676-0](https://doi.org/10.1007/s41062-026-02676-0)

[P00067 | 13343:13558 | NORMAL_TEXT]
Federal Highway Administration. (2025). Updated crash costs for highway safety analysis (Report No. FHWA-SA-25-021). [https://highways.fhwa.dot.gov/sites/fhwa.dot.gov/files/2025-10/CrashCostFactSheet_508_OCT2025.pdf](https://highways.fhwa.dot.gov/sites/fhwa.dot.gov/files/2025-10/CrashCostFactSheet_508_OCT2025.pdf)

[P00068 | 13558:13767 | NORMAL_TEXT]
Finley, M. D., & Ullman, G. L. (2023). Commercial motor vehicle safety in work zones targeted action plan (Report No. FHWA-HOP-20-027). Federal Highway Administration. [https://rosap.ntl.bts.gov/view/dot/72451](https://rosap.ntl.bts.gov/view/dot/72451)

[P00069 | 13767:14017 | NORMAL_TEXT]
Madireddy, S., Gao, L., Din, Z., Kim, K., Senouci, A., Han, Z., & Zhang, Y. (2025). Large language model-driven code compliance checking in building information modeling. Electronics, 14(11), Article 2146. [https://doi.org/10.3390/electronics14112146](https://doi.org/10.3390/electronics14112146)

[P00070 | 14017:14291 | NORMAL_TEXT]
Overall, M. W., Mukai, J., Sakhare, R. S., Desai, J., Horton, D., & Bullock, D. M. (2026). Applications of commercial truck dash cameras for work zone inspection and monitoring. Journal of Transportation Technologies, 16(1), 95–114. [https://doi.org/10.4236/jtts.2026.161006](https://doi.org/10.4236/jtts.2026.161006)

[P00071 | 14291:14478 | NORMAL_TEXT]
Peng, J., & Liu, X. (2023). Automated code compliance checking research based on BIM and knowledge graph. Scientific Reports, 13, Article 7065. [https://doi.org/10.1038/s41598-023-34342-1](https://doi.org/10.1038/s41598-023-34342-1)

[P00072 | 14478:14742 | NORMAL_TEXT]
Qian, S., Guengerich, Q., & Tao, T. (2024). Mitigating crash risks in work zones: Causal inference and crash modification factors. Carnegie Mellon University, Traffic21 Institute, Safety21 University Transportation Center. [https://rosap.ntl.bts.gov/view/dot/77512](https://rosap.ntl.bts.gov/view/dot/77512)

