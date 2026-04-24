# PROJECT PROBLEM STATEMENT

## 1. Problem
Retail investors and analysts face significant difficulty in making timely, evidence-based stock decisions due to the fragmented nature of financial information. Critical data required for informed decision-making is distributed across multiple sources, each demanding a different mode of analysis and interpretation. These sources typically include market trend data, technical indicators, company fundamentals, and macroeconomic signals.

In practice, each of these components is reviewed independently. Market trends are analyzed through price movement and sentiment, technical indicators through chart patterns and signals, fundamentals through financial statements and ratios, and macro conditions through economic and policy developments. Because these analyses exist in isolation, users must manually consolidate insights to form a coherent view.

This workflow introduces several challenges. It is time-consuming, requiring users to switch between tools and contexts. It is inconsistent, as different users may weigh factors differently or overlook key signals. Most importantly, it is vulnerable to subjective bias, where decisions may be influenced more by intuition or selective interpretation than by a balanced, structured evaluation of all relevant factors.

## 2. Target Users
The primary users of this system are retail investors, finance learners, and analysts. These users vary in experience but share a common need for structured and reliable stock analysis.

Retail investors often lack access to institutional-grade tools and must rely on scattered resources, making their decision process inefficient and error-prone. Finance learners require clear, structured outputs that help them understand how different analytical components contribute to a final investment decision. Analysts, while more experienced, still benefit from a system that accelerates analysis and enforces consistency across evaluations.

Across all user groups, the common requirement is the ability to quickly evaluate both individual stocks and comparisons between two stocks in a consistent and interpretable manner.

## 3. User Need
Users need a unified system that can process a natural-language stock query and produce a comprehensive, decision-ready output. Instead of manually gathering and interpreting data, users should be able to ask a question in plain language and receive a structured response.

The output must cover five key dimensions of analysis:
- Market trend
- Technical signal
- Fundamental view
- Macro rating
- Final synthesized recommendation

Beyond simply presenting these components, the system must also provide actionable guidance. This includes the level of conviction in the recommendation, an assessment of risk, and guidance on position sizing. The output should be clear, structured, and immediately usable for decision-making while preserving transparency in how conclusions are reached.

## 4. Specific Problem the AI Agent Will Solve
The system must automatically generate a complete and structured stock analysis across five distinct analytical pillars: Market, Technical, Fundamental, Macro, and Synthesis.

Each pillar represents a different dimension of reasoning and must produce outputs that are internally consistent and aligned with the others. Intermediate findings should not exist in isolation; instead, they must be traceable and contribute logically to the final recommendation.

The system must ensure that:
- Each analytical stage produces clear, structured outputs
- Outputs from earlier stages are correctly interpreted and used in later stages
- Conflicts between signals (e.g., strong technicals but weak fundamentals) are explicitly recognized and resolved in the synthesis

By solving this problem, the system enables users to understand not only the final recommendation but also the full context behind it. This includes how technical momentum interacts with fundamental strength, how macro conditions influence risk, and how all factors combine into a coherent investment view.

## 5. Why an Agentic Approach Is Suitable
The problem requires multiple distinct capabilities that cannot be reliably handled within a single, monolithic prompt. These capabilities include retrieving market-related information, enriching context, interpreting technical indicators, analyzing fundamentals, assessing macroeconomic conditions, and synthesizing all findings into a final recommendation.

An agentic architecture is suitable because it allows specialized agents to handle each stage of the workflow independently while maintaining structured communication between them. Each agent can focus on a specific analytical responsibility, ensuring depth, consistency, and clarity within its domain.

By passing structured outputs from one stage to the next, the system improves reliability and reduces ambiguity. This modular approach also enhances traceability, as each step in the analysis can be examined and validated. Ultimately, this leads to higher-quality, end-to-end decision support while preserving the logical flow from raw inputs to final recommendation.

