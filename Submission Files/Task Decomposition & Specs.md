# PROJECT PROBLEM STATEMENT

## 1. Problem
Retail investors and analysts often struggle to make timely, evidence-based stock decisions. Relevant information is distributed across multiple sources, and each source requires a different type of analysis. Market trends, technical indicators, fundamental metrics, and risk controls are typically reviewed separately and then combined manually. This workflow is slow, inconsistent, and vulnerable to subjective bias.

## 2. Target Users
Primary users are retail investors, finance learners, and analysts who need fast, structured insights for both single-stock analysis and two-stock comparison.

## 3. User Need
Users need a single system that can accept a natural-language stock query and return a decision-ready output. The output should include:
- Market trend  
- Technical signal  
- Fundamental view  
- Macro rating  
- Final recommendation with:
  - Conviction  
  - Risk level  
  - Position size guidance  

## 4. Specific Problem the AI Agent Will Solve
The system must automatically produce a complete and structured analysis across five distinct pillars:
- Market  
- Technical  
- Fundamental  
- Macro  
- Synthesis  

It must ensure that intermediate findings are:
- Consistent  
- Traceable  
- Aligned across all stages  

This enables users to understand the full context behind a recommendation, from technical momentum to regulatory risks.

## 5. Why an Agentic Approach Is Suitable
This problem requires distinct capabilities across stages, including:
- Market data retrieval  
- Context enrichment  
- Technical interpretation  
- Fundamental reasoning  
- Governed final synthesis  

A single prompt is not reliable for handling this full workflow. An agentic architecture is suitable because specialist agents can own each stage and pass structured outputs forward, improving:
- Reliability  
- Modularity  
- End-to-end decision quality  