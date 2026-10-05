# ATS screen brief (for screening subagents)

You are screening job postings against one candidate's CV. Read the CV file you were given in full first.
For each posting in your batch file, act as a recruiter doing a fast first screen: does this CV clear the
role's hard requirements and would it be shortlisted?

Candidate in one line (the CV file wins on any detail): London-based senior enterprise seller, about 15 years.
SAP (FSI), Misys/Finastra (Global Account Manager, banking software), Microsoft (FSI Sales Lead CEE, about $100M),
Foresight (fintech, data analytics), SAS (Enterprise / Growth Sector Manager, $17M ARR, FSI, data management,
analytics, AI), DataWave (2024 to present, founding commercial lead, AI and data). INSEAD EMBA, Oxford.
No foreign languages on the CV. No public sector, education, healthcare, cybersecurity or IAM, MarTech, CPQ,
Middle East or Nordics track record on the CV.

## Scoring

Score 0 to 100 for how well the CV matches the JD's stated requirements: motion, seniority, domain, buyer or vertical,
location and hard requirements.

- **Pursue**: score 75 or more AND no structural gap.
- **Skip**: score below 60 AND at least one structural gap on a high-priority requirement.
- **Borderline**: everything else.

A structural gap is something a recruiter rejects on regardless of other strengths:
- a required language that is not on the CV
- a required vertical or sector track record that is absent (public sector, education, healthcare, defence and so on)
- a required specialism that is absent (cybersecurity, IAM, MarTech, CPQ and so on)
- a required regional track record that is absent, or security clearance required
- a role that is clearly junior (SDR, BDR, SMB, mid-market, commercial) or not a quota-carrying sales role
- a fixed-term contract, a recruitment-agency posting, or a people-manager role leading a team of sellers
- a location outside the UK or remote-UK

An adjacent domain on its own is not structural; that is what Borderline is for.

Judgement rules learned from earlier runs:
- The FLAGS line is a regex scan of the full JD; the JD text you see is cut at 2,400 characters. Treat a flagged
  language or clearance as required only when the wording makes it required. "Preferred", "a plus", "an advantage"
  or "ideally" are not requirements. If the requirement wording is cut off, say so in the reason.
- A company headquartered in the US, or legal boilerplate naming US states, is not a location gap when the role is UK-based.
- Quote only facts that are in the CV file. Do not invent figures, employers or partners (earlier runs invented
  "KPMG co-sell" and "NRR 110 to 120 percent"; both were wrong).

## Calibration examples (same method, earlier screens)

```
W49|80|Pursue|AI/data platform selling into regulated FTSE accounts with MEDDPICC maps directly to SAS and DataWave experience.
W54|82|Pursue|Experian data quality sale with MEDDPICC lines up with SAS data management and FSI buyer relationships.
W58|76|Pursue|Financial crime compliance SaaS sold to banks, fintechs and payments matches his FSI buyer base and MEDDICC practice.
W56|72|Borderline|Elastic data/search platform and MEDDPICC fit well but technical fluency in observability and security is a partial gap.
W52|68|Borderline|ERP/EAM/FSM sale draws partially on SAP background but asset-heavy industries are not his vertical.
W75|62|Borderline|Enterprise payments hunter fits fintech heritage but the Travel, Ticketing and Hospitality vertical is not on the CV.
W62|40|Skip|German fluency is required and not on the CV.
W67|48|Skip|8+ years of public sector B2B sales is a hard requirement and absent from the CV.
W78|58|Skip|Enterprise sales specifically in cybersecurity or data protection is required; neither is on the CV.
```

## Output

Write one line per posting, in batch order, to your output file, exactly:
`<key>|score|Verdict|one-sentence reason`
using the keys as they appear in the batch (for example K007). The reason is one sentence naming the decisive fit or gap,
with no em dashes, no pipe characters and at most about 200 characters. Every key appears exactly once.
Append as you go so partial work survives. Afterwards, check with a short script that every batch key appears once
and every verdict is Pursue, Borderline or Skip.

Read only this brief, the CV file, your batch file and your own output file. No network calls and no Notion.
Final reply: counts per verdict, the Pursue keys with company names, and any judgement calls worth a human look.
