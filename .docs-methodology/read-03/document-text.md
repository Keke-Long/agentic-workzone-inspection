# workzone论文

- Document ID: 1e3KD9OhqH2JJFUhKSBKqXsOFD_YIzEOtp8wBPTfjZeQ
- Revision ID: AHj4eMTuUBKYKeNoeBbL4z6DjLq3YLLHC7dA7M4Q0JitKjK7M2gzlw7om6IC0niDR3gimUA6Xck2uhieCKXV2xzma0IbWKPw-KqKpastfJI
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

[P00022 | 6462:7121 | NORMAL_TEXT]
The proposed framework converts connected-vehicle observations into work-zone inspection records through four stages: layout selection, regulation-grounded inspection planning, tool-assisted inspection and assessment, and inspection report synthesis (Fig. 1). The sensing inputs are vehicle-mounted camera imagery and LiDAR point clouds, with the calibration and synchronization information needed by the analysis tools. Telematics data are not an input to the framework. A multimodal agent connects these observations with a structured representation of the Manual on Uniform Traffic Control Devices (MUTCD), 11th Edition, and a set of scene-evidence tools.

[P00023 | 7121:7799 | NORMAL_TEXT]
The framework separates deciding what should be inspected from establishing what the observations can support. Stage 1 selects a source-supported Typical Application (TA). Stage 2 uses structure-guided retrieval-augmented generation (RAG) to identify candidate provisions, construct explicit inspection requirements, and plan evidence acquisition. Stage 3 executes the plan and forms evidence-supported judgments. Stage 4 assembles the results into a report that links each requirement to its normative source, observations, measurements, and assessment rationale. Evidence-insufficient items remain visible as not_assessed rather than being omitted or treated as satisfactory.

[P00024 | 7799:7801 | NORMAL_TEXT]
[INLINE_OBJECT kix.qile3ot6k6yg]

[P00025 | 7801:7802 | NORMAL_TEXT]
⟦EMPTY PARAGRAPH⟧

[P00026 | 7802:7865 | NORMAL_TEXT]
Fig. 1. Four-stage framework for agentic work-zone inspection.

[P00027 | 7865:7895 | HEADING_2]
2.2 Stage 1: Layout Selection

[P00028 | 7895:8424 | NORMAL_TEXT]
Layout selection establishes the traffic-control configuration that organizes subsequent regulatory retrieval. The agent uses the available scene context to distinguish features such as the closed lane, direction of traffic, merging transition, lane shift, and presence of conditional devices. Known facts are recorded with their provenance; an unknown condition remains unknown rather than being interpreted as false. Camera observations provide visual context, while geometric information is used where available and relevant.

[P00029 | 8424:8880 | NORMAL_TEXT]
The agent searches the MUTCD Typical Applications and examines their source descriptions, diagrams, and associated notes before selecting the applicable layout. The output is a TA identifier, the supporting source references, and a scene-based selection rationale. Selecting a TA narrows the regulatory search space. The selected TA and scene facts are passed to Stage 2 so that both layout-specific and condition-dependent requirements can be considered.

[P00030 | 8880:8933 | HEADING_2]
2.3 Stage 2: Regulation-Grounded Inspection Planning

[P00031 | 8933:9332 | NORMAL_TEXT]
This stage transforms regulatory knowledge into an executable inspection plan. Its methodological contribution is the explicit connection between the manual's structure, scene-conditioned requirement activation, and the evidence needed to evaluate each requirement. It comprises three modules: structured regulatory retrieval, applicable requirement construction, and evidence acquisition planning.

[P00032 | 9332:9370 | HEADING_3]
2.3.1 Structured Regulatory Retrieval

[P00033 | 9370:9915 | NORMAL_TEXT]
The regulatory representation preserves the MUTCD's source organization, including sections, Typical Applications, clauses, figure components, tables, notes, and explicit cross-references. A knowledge graph (KG) connects source units and their relevant relationships, while retained source locators and text spans allow retrieved information to be checked against the manual. This representation is constructed independently of the evaluation answers; benchmark requirement identifiers and expected inspection outcomes are not retrieval inputs.

[P00034 | 9915:10617 | NORMAL_TEXT]
Candidate generation combines three complementary layers. First, a TA-core layer retrieves provisions connected to the selected Typical Application, including relevant components and referenced material. Second, a scene-condition layer activates additional KG candidates using the recorded scene facts and identified components. Third, a gap-retrieval layer searches for potentially relevant provisions beyond the graph-derived candidate set. The primary method uses BM25 for this supplementary search; a dense retriever is a method variant. The two graph layers supply deterministic candidates, while supplementary retrieval broadens the candidate pool without replacing the graph-derived provisions.

[P00035 | 10617:11180 | NORMAL_TEXT]
The candidate set can be expressed as C = C_TA ∪ C_scene ∪ C_gap, where C_TA denotes the TA-core candidates, C_scene denotes candidates activated by scene conditions, and C_gap denotes supplementary retrieval results. Candidate retrieval is organized around six inspection domains: lane-closure layout, advance-warning signs, channelization, transition and taper geometry, conditional active devices, and the conditional termination area. These domains bound the current inspection scope; the framework does not claim exhaustive coverage of all MUTCD provisions.

[P00036 | 11180:11703 | NORMAL_TEXT]
The structure-guided RAG contribution therefore lies in preserving the relationship between a retrieved provision, its governing context, and the observed configuration. A textually similar passage is treated as a candidate, not immediately as an applicable requirement. The graph-based and supplementary results are passed together to the next module, where applicability is explicitly resolved and recorded. This separation also permits retrieval coverage and requirement-selection quality to be evaluated independently.

[P00037 | 11703:11745 | HEADING_3]
2.3.2 Applicable Requirement Construction

[P00038 | 11745:12330 | NORMAL_TEXT]
The agent converts the candidate pool into atomic requirements that can be assessed separately. For every deterministic KG candidate, it records a structured decision comprising the activation state (established, false, or unknown), whether the candidate represents an independently violable requirement, any duplicate source relationship, the retain-or-exclude action, the decision basis, and the measurement specification. An initial compilation may be followed by a candidate audit, but unresolved KG candidates must receive a decision before the requirement registry is finalized.

[P00039 | 12330:12961 | NORMAL_TEXT]
For each retained item, the system binds the inspected subject, required relation or condition, threshold where specified, normative modality, applicability conditions, required evidence inputs, and authoritative source locator and span. Mandatory provisions and guidance retain their different normative force. Unknown activation conditions remain explicit in the decision record; retaining an item is not evidence that all of its preconditions have been established. Each requirement receives a run-local key for linking planning, evidence, and conclusions, while the MUTCD locator remains the authoritative regulatory citation.

[P00040 | 12961:13412 | NORMAL_TEXT]
This structured compilation limits the loss of conditions and source context that can occur when retrieved passages are summarized into free-form inspection questions. It also distinguishes requirement applicability from observability: a requirement cannot be excluded solely because the available traversal lacks the evidence needed to assess it. Such limitations are carried forward to evidence planning and, if unresolved, to the final assessment.

[P00041 | 13412:13448 | HEADING_3]
2.3.3 Evidence Acquisition Planning

[P00042 | 13448:13963 | NORMAL_TEXT]
For each registered requirement, the agent identifies the observations or measurements needed to support a judgment and checks their availability in the scene data. The planning record distinguishes information already available, information that is only partially available, and acquisition that has not yet been attempted. It specifies the relevant tool family, target objects or frames, required inputs, and the measurement or observation to be returned. No compliance conclusion is produced during this module.

[P00043 | 13963:14549 | NORMAL_TEXT]
The plan follows the semantics of the requirement. A device-condition check requires visual evidence of the relevant device and its condition; a spacing or taper check requires suitable geometric observations and any inputs needed to instantiate the registered threshold. Detecting a device alone does not establish its condition, position, or spacing. When an input is unavailable, the limitation is recorded explicitly rather than replaced with an assumed value. Stage 2 ends with a source-linked requirement registry and an evidence acquisition plan that guide execution in Stage 3.

[P00044 | 14549:14602 | HEADING_2]
2.4 Stage 3: Tool-Assisted Inspection and Assessment

[P00045 | 14602:15223 | NORMAL_TEXT]
The agent executes the acquisition plan through the available scene-evidence tools. These tools expose accepted object observations, image references, device attributes, and geometric measurements where the sensor data support them. Each returned result is attached to the corresponding requirement key, together with its provenance, such as the frame, object identifier, bounding box, measurement inputs, and validity information. The language model coordinates tool use and interprets returned evidence; numerical measurements are obtained through the measurement tools rather than invented from the narrative context.

[P00046 | 15223:15759 | NORMAL_TEXT]
Execution is informed by intermediate results. When evidence is incomplete, the agent can request further available observations or measurements before finalizing the evidence record. Tool failures and unresolved inputs are retained as acquisition limitations. This process is constrained by the available tools and data: repeated requests do not justify assuming that missing evidence exists. Before assessment, the evidence record accounts for the required inputs of each registered item, including inputs that could not be obtained.

[P00047 | 15759:16352 | NORMAL_TEXT]
The assessment then compares the bound evidence with the registered requirement. An item is satisfied when sufficient valid evidence supports the specified condition, deficient when sufficient valid evidence supports a departure from that condition, and not_assessed when the available evidence does not support either conclusion. Numeric checks use the registered relation, threshold or formula, units, and required contextual inputs. Qualitative checks cite the observations that support the judgment. An acquisition failure or an unobserved device is not, by itself, proof of a deficiency.

[P00048 | 16352:16864 | NORMAL_TEXT]
Although acquisition and assessment form one stage in the conceptual framework, evidence recording precedes conclusion formation. Each registered requirement receives one final status with a rationale and evidence references. The assessment preserves the distinction between a mandatory requirement and guidance, so that a reported departure is interpreted with the normative force of its source. Requirements and source bindings established in Stage 2 are not silently rewritten to fit downstream observations.

[P00049 | 16864:16905 | HEADING_2]
2.5 Stage 4: Inspection Report Synthesis

[P00050 | 16905:17453 | NORMAL_TEXT]
The final stage converts the structured assessment records into a readable inspection report. The report begins with the scene identifier, selected layout, inspection scope, and a summary of assessed and unassessed requirements. A requirement-level results table presents the inspected condition, normative class, MUTCD source, outcome, and associated issue or evidence references. Detailed evidence records provide the supporting images or image regions, relevant measurements, and the explanation connecting those observations to the conclusion.

[P00051 | 17453:18012 | NORMAL_TEXT]
The report distinguishes regulatory findings from physical issues. When several requirements refer to the same observed defect, their individual conclusions remain in the results table, while a consolidated issue entry groups the shared evidence. A separate coverage-gap section lists not_assessed items and explains the missing evidence or unresolved measurement inputs. This organization allows a reviewer to distinguish observed deficiencies from limits of the inspection and to identify which additional observations would be needed for follow-up review.

[P00052 | 18012:18602 | NORMAL_TEXT]
Report synthesis is a presentation step: it preserves the finalized requirement registry, evidence bindings, and judgments without introducing new applicability decisions or unsupported conclusions. The resulting trace from source provision to requirement, tool evidence, and final status is retained in both structured records and the human-readable report. Applying the framework to another work zone changes the scene facts, selected TA, activated requirements, and evidence plan while retaining the same regulatory representation, decision schema, tool interfaces, and reporting logic.

[P00053 | 18602:18625 | HEADING_1]
3. Experimental Design

[P00054 | 18625:18641 | HEADING_2]
3.1 Data Source

[P00055 | 18641:18760 | NORMAL_TEXT]
Data were collected at two work zones in Madison, Wisconsin, using our laboratory's Level 3 automated driving vehicle.

[P00056 | 18760:18819 | NORMAL_TEXT]
[Camera and LiDAR models and dataset details to be added.]

[P00057 | 18819:18840 | HEADING_2]
3.2 Compared Systems

[P00058 | 18840:19070 | NORMAL_TEXT]
Baseline 1 — Direct multimodal judgment: Available images and scene text are provided directly to a multimodal model, which produces an inspection judgment without external regulatory, perception, geometry, or localization tools.

[P00059 | 19070:19441 | NORMAL_TEXT]
Baseline 2 — Rule-based if–then workflow: Prespecified scene-profile conditions and inspection items trigger a fixed, human-authored tool chain. The workflow may read the same scene profile as the proposed approach, but the selected tools and their order are determined in advance. It does not replan in response to retrieval results, tool failures, or evidence quality.

[P00060 | 19441:19752 | NORMAL_TEXT]
Proposed — Agentic workflow: The agent receives the same inputs but determines applicable tasks and tool order dynamically. It may continue, switch, retry, narrow a task, stop, or request human review based on regulatory retrieval and intermediate tool outputs, while preserving a complete evidence trajectory.

[P00061 | 19752:19778 | HEADING_2]
3.3 Tool-Level Evaluation

[P00062 | 19778:20294 | NORMAL_TEXT]
Visual detection will be evaluated using precision, recall, F1, and/or mAP as appropriate to the selected model and annotation unit. Device-condition classification will use per-class precision, recall, and F1. Geometric measurement will use mean absolute error, root mean squared error, and valid-measurement rate. Structure-guided RAG will be evaluated through applicability retrieval, Recall@k for governing sources, final citation correctness, and correctness of extracted conditions and numerical requirements.

[P00063 | 20294:20326 | HEADING_2]
3.4 Inspection-Level Evaluation

[P00064 | 20326:20705 | NORMAL_TEXT]
For applicable and observable items, the study will report inspection-status accuracy, macro-F1, and item-specific performance. Not observable and requires human review will be evaluated as explicit system behaviors using coverage, selective accuracy, and unnecessary-review rate. This treatment prevents abstention from being counted automatically as either success or failure.

[P00065 | 20705:20743 | HEADING_2]
3.5 Agent and System-Level Evaluation

[P00066 | 20743:21239 | NORMAL_TEXT]
System evaluation will report inspection-item selection accuracy, tool selection accuracy, valid execution-plan rate, successful completion rate, evidence-field completeness, regulatory and observation traceability, execution time, and computational cost. Agent traces will also be categorized by whether they continued, switched tools, retried, narrowed the task, stopped, or requested review, allowing the claimed adaptive behavior to be measured rather than illustrated only through examples.

[P00067 | 21239:21271 | HEADING_2]
3.6 Human Evaluation of Reports

[P00068 | 21271:21581 | NORMAL_TEXT]
Reviewers with transportation-engineering knowledge will assess the correctness, clarity, evidentiary support, and practical review value of generated inspection records. The evaluation protocol, reviewer count, rating scale, adjudication procedure, and inter-rater reliability measure remain to be finalized.

[P00069 | 21581:21618 | HEADING_2]
3.7 Ablation and Diagnostic Analysis

[P00070 | 21618:22066 | NORMAL_TEXT]
Ablations will isolate the effects of manual structure guidance, dynamic planning, and access to selected sensing tools. Diagnostic analysis will separate errors in scene understanding, applicability determination, retrieval, object detection, condition assessment, geometry, tool selection, deterministic comparison, and evidence aggregation. The final ablation set will be limited to comparisons that directly support the two research questions.

[P00071 | 22066:22077 | HEADING_1]
4. Results

[P00072 | 22077:22208 | NORMAL_TEXT]
This section intentionally contains no assumed results. Tables and figures below define the outputs required from the experiments.

[P00073 | 22208:22247 | HEADING_2]
4.1 Structure-Guided Retrieval Results

[P00074 | 22247:22517 | NORMAL_TEXT]
Table 1 (to be completed): retrieval and requirement-extraction performance for unstructured retrieval and Structure-guided RAG. Include governing-source Recall@k, applicability accuracy, citation correctness, condition extraction, and numerical requirement extraction.

[P00075 | 22517:22540 | HEADING_2]
4.2 Tool-Level Results

[P00076 | 22540:22775 | NORMAL_TEXT]
Table 2 (to be completed): performance of visual detection and condition assessment by device class. Table 3 (to be completed): geometric measurement error and valid-measurement rate by range, device type, and sensing-quality stratum.

[P00077 | 22775:22809 | HEADING_2]
4.3 End-to-End Inspection Results

[P00078 | 22809:23020 | NORMAL_TEXT]
Table 4 (to be completed): item-level inspection accuracy, macro-F1, coverage, selective accuracy, and review rate for Direct multimodal judgment, Rule-based if–then workflow, and the proposed Agentic workflow.

[P00079 | 23020:23054 | HEADING_2]
4.4 Planning and Tool-Use Results

[P00080 | 23054:23234 | NORMAL_TEXT]
Table 5 (to be completed): inspection-item selection, tool selection, plan validity, completion, evidence completeness, traceability, runtime, cost, and observed adaptive actions.

[P00081 | 23234:23280 | HEADING_2]
4.5 Representative Cases and Failure Analysis

[P00082 | 23280:23642 | NORMAL_TEXT]
Figure 1 (to be developed): system overview. Figure 2 (to be developed): Structure-guided RAG and dynamic execution loop. Figure 3 (to be completed): representative end-to-end evidence trace. Figure 4 (to be completed): successful geometric inspection using synchronized image and point-cloud evidence. Table 6 (to be completed): failure taxonomy and frequency.

[P00083 | 23642:23657 | HEADING_1]
5. Conclusions

[P00084 | 23657:24010 | NORMAL_TEXT]
This study develops a structure-guided agentic workflow for converting connected-vehicle observations into traceable work-zone inspection records. The final conclusion will be written after experiments establish the reliability of the component tools, the value of dynamic orchestration, the supported inspection scope, and the principal failure modes.

[P00085 | 24010:24021 | HEADING_1]
References

[P00086 | 24021:24251 | NORMAL_TEXT]
Alnuzha, M., & Bloch, T. (2026). Integrating large language models and knowledge graphs for adaptive design review. Journal of Information Technology in Construction (ITcon), 31, 888–916. [https://doi.org/10.36680/j.itcon.2026.038](https://doi.org/10.36680/j.itcon.2026.038)

[P00087 | 24251:24552 | NORMAL_TEXT]
Beach, T., Yeung, J., Ghoroghi, A., & Rezgui, Y. (2025). Moving automated compliance checking to the operational phase of the building life-cycle: Analysis and feasibility study in the UK. International Journal of Construction Management, 25(7), 840–849. [https://doi.org/10.1080/15623599.2024.2366727](https://doi.org/10.1080/15623599.2024.2366727)

[P00088 | 24552:24835 | NORMAL_TEXT]
Beach, T., Yeung, J., Nisbet, N., & Rezgui, Y. (2024). Digital approaches to construction compliance checking: Validating the suitability of an ecosystem approach to compliance checking. Advanced Engineering Informatics, 59, Article 102288. [https://doi.org/10.1016/j.aei.2023.102288](https://doi.org/10.1016/j.aei.2023.102288)

[P00089 | 24835:25151 | NORMAL_TEXT]
Chan, C. F., Wong, K. Y., Guo, X., Cheng, J. C. P., Chan, J. P. C., Leung, P. H., & Tao, X. (2025). Context-aware vision-language model agent enriched with domain-specific ontology for construction site safety monitoring. Automation in Construction, 177, Article 106305. [https://doi.org/10.1016/j.autcon.2025.106305](https://doi.org/10.1016/j.autcon.2025.106305)

[P00090 | 25151:25377 | NORMAL_TEXT]
Dwairi, M., Manasreh, D., Melhem, M., & Nazzal, M. D. (2026). Automated traffic signs condition monitoring using machine vision. Innovative Infrastructure Solutions, 11, Article 325. [https://doi.org/10.1007/s41062-026-02676-0](https://doi.org/10.1007/s41062-026-02676-0)

[P00091 | 25377:25592 | NORMAL_TEXT]
Federal Highway Administration. (2025). Updated crash costs for highway safety analysis (Report No. FHWA-SA-25-021). [https://highways.fhwa.dot.gov/sites/fhwa.dot.gov/files/2025-10/CrashCostFactSheet_508_OCT2025.pdf](https://highways.fhwa.dot.gov/sites/fhwa.dot.gov/files/2025-10/CrashCostFactSheet_508_OCT2025.pdf)

[P00092 | 25592:25801 | NORMAL_TEXT]
Finley, M. D., & Ullman, G. L. (2023). Commercial motor vehicle safety in work zones targeted action plan (Report No. FHWA-HOP-20-027). Federal Highway Administration. [https://rosap.ntl.bts.gov/view/dot/72451](https://rosap.ntl.bts.gov/view/dot/72451)

[P00093 | 25801:26051 | NORMAL_TEXT]
Madireddy, S., Gao, L., Din, Z., Kim, K., Senouci, A., Han, Z., & Zhang, Y. (2025). Large language model-driven code compliance checking in building information modeling. Electronics, 14(11), Article 2146. [https://doi.org/10.3390/electronics14112146](https://doi.org/10.3390/electronics14112146)

[P00094 | 26051:26325 | NORMAL_TEXT]
Overall, M. W., Mukai, J., Sakhare, R. S., Desai, J., Horton, D., & Bullock, D. M. (2026). Applications of commercial truck dash cameras for work zone inspection and monitoring. Journal of Transportation Technologies, 16(1), 95–114. [https://doi.org/10.4236/jtts.2026.161006](https://doi.org/10.4236/jtts.2026.161006)

[P00095 | 26325:26512 | NORMAL_TEXT]
Peng, J., & Liu, X. (2023). Automated code compliance checking research based on BIM and knowledge graph. Scientific Reports, 13, Article 7065. [https://doi.org/10.1038/s41598-023-34342-1](https://doi.org/10.1038/s41598-023-34342-1)

[P00096 | 26512:26776 | NORMAL_TEXT]
Qian, S., Guengerich, Q., & Tao, T. (2024). Mitigating crash risks in work zones: Causal inference and crash modification factors. Carnegie Mellon University, Traffic21 Institute, Safety21 University Transportation Center. [https://rosap.ntl.bts.gov/view/dot/77512](https://rosap.ntl.bts.gov/view/dot/77512)

