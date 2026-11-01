# AI company watchlist: who runs competitions, and where

Research done 2026-11-01, after the radar missed ElevenLabs' "The Search"
($100K for the world's catchiest AI-made ad, entries closed 1 Nov 2026
11:59pm PST). The question: across 100 of the largest AI companies, which
ones run competitions, and would the radar have seen them?

The list itself lives in `buildathon_radar/ai_companies.py`; the table below
is generated from it. "Record" is what web research found (mostly 2025-2026
events); entries marked "None found" mean nothing turned up, not that the
company never runs one. Prize figures come partly from third-party listings
and were not all verified against official pages.

## What the research found

1. **The radar's sources only catch part of it.** Devpost carries the big
   developer hackathons from Google, AWS, NVIDIA, Salesforce, and Alibaba,
   and the radar already sees those. But many competitions live elsewhere:
   - **Company-run pages**: ElevenLabs (The Search, ElevenHacks), Runway
     (Gen:48, AI Festival), Luma AI (Dream Brief, $1M), Higgsfield
     (Adathon, $85K), Adobe Firefly challenges, Supabase launch-week
     hackathons, Anthropic's "Built with Claude" series.
   - **lablab.ai**: Meta Llama Impact, IBM watsonx, Cohere, Groq,
     Cerebras, ElevenLabs online hackathons.
   - **Kaggle**: OpenAI (gpt-oss red-teaming, $500K), Google, Gemma.
   - **DEV (dev.to) challenges**: Google AI, Notion MCP, n8n.
   - **Hugging Face Spaces**: Agents & MCP, "Build Small" ($40K+).
   - **Luma pages outside Bengaluru**: Mistral Worldwide Hackathon
     (7 cities + online), Cursor community hackathons.
   - **Cerebral Valley** (built but switched off): Anthropic's
     "Built with Claude" online hackathons are run with them.
2. **Creative contests are a distinct, growing class.** Generative media
   companies (ElevenLabs, Runway, Luma AI, Higgsfield, Kling, Adobe) run
   ad, film, music, and design contests with big prizes. None appear on
   hackathon platforms, and the old rubric scored them low because the
   entry is creative work, not software.
3. **About a third of the list runs nothing public.** Enterprise AI apps
   (Harvey, Sierra, Decagon, Abridge), some labs (DeepSeek, SSI, Thinking
   Machines), and infra players mostly sponsor other people's hackathons
   rather than running their own. They stay on the list because the news
   search costs nothing extra per company.

## What changed in the radar

- **Watchlist source** (`fetch_watchlist` in `fetcher.py`): every week, a
  Bing News search for each company plus contest words (hackathon,
  contest, competition, challenge, prize pool), last 8 days only. Results
  are filtered for a contest signal, for market-competition and
  winners-announced headlines, and capped (2 per company, 30 total)
  before they reach Claude. It catches anything that gets press or a
  company blog post, whatever platform it's hosted on.
- **Rubric** (`agent.py`): AI creative contests run by a major AI company
  with its own tools now score 22 to 30 on theme fit. Watchlist items are
  explained to Claude as announcements, and anything not enterable
  (funding news, closed contests) is excluded.

## Possible follow-ups (not built)

- A direct lablab.ai source: it is the densest single venue for
  sponsor-run AI hackathons the radar does not cover.
- Turn on Cerebral Valley (`ENABLE_CV_SOURCE`), which was due around
  2026-07-22 and would catch Anthropic's hackathon series directly.
- Kaggle needs an API key; DEV challenges have a public page per challenge.

## The 100 companies

| # | Company | Category | Competition record | Usual venues | Radar source covers it? |
|---|---|---|---|---|---|
| 1 | Google | Big tech | Frequent: Build with Gemini XPRIZE ($2M, 2026), Kaggle competitions, Gemma hackathons, DEV challenges | Devpost, Kaggle, DEV, Company site | Partly |
| 2 | Microsoft | Big tech | Frequent: AI agents hackathons, Azure hackathon series, Imagine Cup (students only) | Devpost, Company site | Partly |
| 3 | Amazon Web Services | Big tech | Frequent: Agents for Humans Hackathon ($40K, 2026), AWS-backed vibe coding hackathons | Devpost, Company site | Partly |
| 4 | NVIDIA | Big tech | Regular: Nebius x NVIDIA Global AI Hackathon (2026), developer contests, Kaggle sponsorships | Devpost, Kaggle, Company site | Partly |
| 5 | Meta | Big tech | Occasional: Llama Impact hackathons and grants (mostly 2024-25) | lablab.ai, Luma, Company site | Partly |
| 6 | Apple | Big tech | Swift Student Challenge (students only); no open AI contests found | Company site | Watchlist only |
| 7 | IBM | Big tech | Regular: watsonx hackathons (up to $15K), Call for Code | lablab.ai, Company site | Watchlist only |
| 8 | Oracle | Big tech | Rare: none found for 2026 | Company site | Watchlist only |
| 9 | Salesforce | Big tech | Yearly: TDX Agentforce hackathon ($50K grand prize, 2026), World Tour Mumbai hackathon | Company site, Devpost | Partly |
| 10 | Adobe | Big tech | Frequent small creative challenges: Firefly community challenges (often region-limited) | Company site | Watchlist only |
| 11 | Samsung | Big tech | Mostly student programmes (Solve for Tomorrow) | Company site | Watchlist only |
| 12 | Intel | Big tech | Occasional AI PC / OpenVINO developer contests | Devpost, Company site | Partly |
| 13 | AMD | Big tech | AMD Developer Challenge / hackathons, mostly GPU-kernel (hardware) focused | lablab.ai, Company site | Watchlist only |
| 14 | Qualcomm | Big tech | Occasional on-device AI developer hackathons | Devpost, Company site | Partly |
| 15 | SAP | Big tech | Occasional SAP BTP / Joule hackathons | Company site | Watchlist only |
| 16 | ServiceNow | Big tech | Occasional developer hackathons (Knowledge conference) | Company site | Watchlist only |
| 17 | Alibaba Cloud | Big tech | Regular Qwen hackathons; excluded by the rubric (cloud account hard to get from India) | Devpost, Company site | Partly |
| 18 | Baidu | Big tech | China-focused contests | Company site | Watchlist only |
| 19 | Tencent | Big tech | China-focused contests | Company site | Watchlist only |
| 20 | ByteDance | Big tech | TikTok TechJam (global, already caught via Devpost in Aug 2026) | Devpost | Yes |
| 21 | OpenAI | Frontier lab | Regular: Kaggle challenges (gpt-oss red-teaming $500K), Build Week, Codex hackathons, OpenAI-supported India hackathons | Kaggle, Company site, Luma, Devfolio | Partly |
| 22 | Anthropic | Frontier lab | Regular: 'Built with Claude' / 'Built with Opus' online hackathons with Cerebral Valley ($50K-$100K credits) | Cerebral Valley, Luma, Company site | Partly |
| 23 | Google DeepMind | Frontier lab | Via Google and Kaggle (Gemma, Gemini competitions) | Kaggle, Devpost | Partly |
| 24 | xAI | Frontier lab | Occasional in-person hackathons (SF) | Company site, Luma | Partly |
| 25 | Mistral AI | Frontier lab | Yearly: Mistral Worldwide Hackathon (7 cities + online, $200K+, Feb-Mar 2026); Gradient Contest (France) | Luma, Company site | Partly |
| 26 | Cohere | Frontier lab | Sponsors hackathons (Hugging Face 'Build Small', lablab.ai events) | lablab.ai, Hugging Face | Watchlist only |
| 27 | AI21 Labs | Frontier lab | Rare | lablab.ai | Watchlist only |
| 28 | DeepSeek | Frontier lab | None found | - | n/a |
| 29 | Moonshot AI | Frontier lab | Occasional developer contests (China-first) | Company site | Watchlist only |
| 30 | Zhipu AI | Frontier lab | Occasional developer contests (China-first) | Company site | Watchlist only |
| 31 | MiniMax | Frontier lab | Creator contests for Hailuo video | Company site | Watchlist only |
| 32 | Thinking Machines Lab | Frontier lab | None found | - | n/a |
| 33 | Safe Superintelligence | Frontier lab | None found | - | n/a |
| 34 | Reflection AI | Frontier lab | None found | - | n/a |
| 35 | Perplexity | AI app | Occasional Sonar API hackathons | Devpost, Company site | Partly |
| 36 | Character.AI | AI app | Occasional creator contests | Company site | Watchlist only |
| 37 | Glean | AI app | Rare | - | n/a |
| 38 | Harvey | AI app | None found | - | n/a |
| 39 | Sierra | AI app | None found | - | n/a |
| 40 | Decagon | AI app | None found | - | n/a |
| 41 | Writer | AI app | Occasional developer hackathons | Company site | Watchlist only |
| 42 | Abridge | AI app | None found | - | n/a |
| 43 | ElevenLabs | Generative media | Very frequent: 'The Search' $100K ad contest (closes Nov 1 2026), ElevenHacks (11 weekly hackathons, $240K+), Worldwide Hackathon (30 cities) | Company site, lablab.ai, AI Tinkerers, Luma | Partly |
| 44 | Runway | Generative media | Yearly: Gen:48 48-hour film sprint, AI Festival (entries close ~April) | Company site | Watchlist only |
| 45 | Midjourney | Generative media | None found | - | n/a |
| 46 | Stability AI | Generative media | None found for 2026 | - | n/a |
| 47 | Black Forest Labs | Generative media | None found | - | n/a |
| 48 | Pika | Generative media | Occasional social creator contests | Company site | Watchlist only |
| 49 | Luma AI | Generative media | Luma Dream Brief: $1M for a Cannes Gold Lion with a Luma-made ad (entries closed Mar 2026) | Company site | Watchlist only |
| 50 | Suno | Generative media | In-app song contests | Company site | Watchlist only |
| 51 | Udio | Generative media | In-app contests | Company site | Watchlist only |
| 52 | Synthesia | Generative media | None found | - | n/a |
| 53 | HeyGen | Generative media | Occasional creator contests | Company site | Watchlist only |
| 54 | Ideogram | Generative media | Occasional community design contests | Company site | Watchlist only |
| 55 | Leonardo.ai | Generative media | Community challenges | Company site | Watchlist only |
| 56 | Krea | Generative media | Occasional creator contests | Company site | Watchlist only |
| 57 | Higgsfield | Generative media | Very frequent: Adathon ($85K with ADWEEK, 2026), Action Scene contest (to Dec 31 2026), weekly creator challenges | Company site | Watchlist only |
| 58 | Kling AI | Generative media | Global creative/film contests | Company site | Watchlist only |
| 59 | Hedra | Generative media | Occasional creator contests | Company site | Watchlist only |
| 60 | Captions | Generative media | None found | - | n/a |
| 61 | Cursor | Dev tools | Community Cursor hackathons in many cities | Luma, lablab.ai | Partly |
| 62 | Cognition | Dev tools | Sponsors hackathons (e.g. ElevenLabs Dubai) | Luma | Yes |
| 63 | Replit | Dev tools | Regular: Replit hackathons and bounties, Replit x TPF Bengaluru sessions | Luma, lablab.ai, Company site | Partly |
| 64 | Lovable | Dev tools | Frequent: Lovable hackathons ($700K+ 'At Scale' with AWS, Mar 2026) | Luma, Company site | Partly |
| 65 | Vercel | Dev tools | Occasional v0 / Next.js hackathons | Devpost, Company site | Partly |
| 66 | StackBlitz (Bolt) | Dev tools | World's Largest Hackathon (2025, $1M+) | Devpost | Yes |
| 67 | GitHub | Dev tools | Occasional Copilot / open source challenges | DEV, Company site | Watchlist only |
| 68 | Windsurf | Dev tools | Occasional | Luma | Yes |
| 69 | Poolside | Dev tools | None found | - | n/a |
| 70 | Sourcegraph | Dev tools | Rare | - | n/a |
| 71 | Warp | Dev tools | Rare | - | n/a |
| 72 | Supabase | Dev tools | Regular: Launch Week hackathons (online, global) | Company site | Watchlist only |
| 73 | Hugging Face | AI infra | Regular: Agents & MCP hackathons, 'Build Small' ($40K+), LeRobot hackathon | Hugging Face, Company site | Watchlist only |
| 74 | Scale AI | AI infra | Occasional paid challenges (e.g. Humanity's Last Exam question bounty) | Company site | Watchlist only |
| 75 | Databricks | AI infra | Occasional Data + AI Summit hackathons | Devpost | Yes |
| 76 | Snowflake | AI infra | Occasional AI-for-good hackathons | Devpost | Yes |
| 77 | Together AI | AI infra | Sponsors hackathons | lablab.ai, Luma | Partly |
| 78 | Fireworks AI | AI infra | Sponsors hackathons | Luma | Yes |
| 79 | Groq | AI infra | Sponsors hackathons | lablab.ai, Luma | Partly |
| 80 | Cerebras | AI infra | Sponsors hackathons | lablab.ai, Luma | Partly |
| 81 | SambaNova | AI infra | Sponsors Hugging Face hackathons | Hugging Face | Watchlist only |
| 82 | CoreWeave | AI infra | None found | - | n/a |
| 83 | Lambda | AI infra | Sponsors hackathons (compute credits) | Luma | Yes |
| 84 | Modal | AI infra | Sponsors hackathons (compute credits) | Luma, Hugging Face | Partly |
| 85 | Replicate | AI infra | Rare | - | n/a |
| 86 | Baseten | AI infra | Rare | - | n/a |
| 87 | Weights & Biases | AI infra | Sponsors hackathons (WeaveHacks) | Luma | Yes |
| 88 | LangChain | AI infra | Occasional | Devpost, Luma | Yes |
| 89 | LlamaIndex | AI infra | Occasional | Devpost, Luma | Yes |
| 90 | Pinecone | AI infra | Occasional | Devpost | Yes |
| 91 | Canva | Platform | Canva developer challenges | Devpost, Company site | Partly |
| 92 | Notion | Platform | Notion MCP Challenge (DEV, 2026) | DEV | Watchlist only |
| 93 | Figma | Platform | Occasional (Config) | Company site | Watchlist only |
| 94 | Zapier | Platform | Rare | - | n/a |
| 95 | n8n | Platform | DEV challenges and community contests | DEV, Company site | Watchlist only |
| 96 | Sarvam AI | India AI | Startup programme (Mar 2026); no open competition found yet | Company site | Watchlist only |
| 97 | Krutrim | India AI | None found | - | n/a |
| 98 | Fractal | India AI | Occasional hackathons | Company site | Watchlist only |
| 99 | Infosys | India AI | HackWithInfy (students only) | Company site | Watchlist only |
| 100 | Tata Consultancy Services | India AI | CodeVita (students mostly) | Company site | Watchlist only |

"Luma" counts as covered only for Bengaluru events; the radar reads the Bengaluru feed only.
