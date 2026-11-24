# Gateway interceptor: route web search by query language

[中文](README.md)

An AgentCore Gateway interceptor (one Lambda at REQUEST + RESPONSE) routes a single
search tool by query language:

- English queries go to **AgentCore Web Search** (`websearch___WebSearch`).
- Chinese queries (>= 30% CJK characters) are rewritten to a third-party MCP search target:
  **AnySearch** (default) or **Bocha**, selected with `deploy.py --cn-provider`.

The agent sees only `websearch___WebSearch`; the third-party tools are hidden from
`tools/list` and rejected on direct call. All providers return one unified result format.

Gateway inbound auth is AWS_IAM (SigV4). Region us-east-1.

## Disclaimer

- This is sample code for demonstration and learning. It is not intended for production use as is.
- Before any production use, you are responsible for your own testing, security review and compliance
  assessment, and for the results of deploying and using it.
- Running this sample incurs AWS charges (AgentCore Gateway, AgentCore Web Search, Lambda, CloudWatch Logs,
  Bedrock model invocations) and third-party search charges. Run `cleanup.py` when you are done.
- This sample sends Chinese queries to third-party services; see [Third-party services](#third-party-services).

## Third-party services

AnySearch and Bocha are **not AWS services**. They are provided and operated independently by their
vendors, and AWS is not responsible for their availability, content, security or data handling. You must
sign up with each provider, obtain your own API key, and accept their terms of service and privacy policy.

| Service | Website | Terms of service | Privacy policy | Pricing |
|---|---|---|---|---|
| AnySearch | https://www.anysearch.com | [Terms of Service](https://www.anysearch.com/legal?type=tos) | [Privacy Policy](https://www.anysearch.com/legal?type=privacy) | [Pricing](https://www.anysearch.com/pricing) |
| Bocha | https://open.bochaai.com | [Terms of Service](https://open.bochaai.com/terms-of-service) | [Privacy Policy](https://open.bochaai.com/privacy-policy) | shown in the Bocha Open Platform console |

**Data sent to the third party**: the text of each query classified as Chinese, and the result count
derived from `maxResults`. The request is sent by AgentCore Gateway, which injects the API key you stored
in AgentCore Identity. Caller identity and request headers are not forwarded (the interceptor uses
`passRequestHeaders: false`). English queries go only to AgentCore Web Search.

Queries can contain personal or business data typed by users. Whether that data may leave AWS for a third
party is your decision, based on your own data classification and compliance requirements.

## Search results are untrusted input

Search results come from the public web and can contain instructions aimed at the model (indirect prompt
injection). The agent must treat them as data, not instructions. `harness_demo.py` says so in its system
prompt, but a prompt alone is not a sufficient defense. In production, add guardrails such as Amazon
Bedrock Guardrails, and add validation or human confirmation before the agent takes any action with side
effects (calling other tools, writing data, sending messages) based on search results.

## Run

```bash
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt   # pinned: boto3/botocore 1.44.5, requests 2.34.2

# store the key(s) you need in AgentCore Identity. read -rs keeps the key out of the terminal and
# shell history; the scripts read it from stdin and never write it to disk.
read -rs ANYSEARCH_KEY && printf %s "$ANYSEARCH_KEY" | .venv/bin/python store_anysearch_key.py
read -rs BOCHA_KEY && printf %s "$BOCHA_KEY" | .venv/bin/python store_bocha_key.py
unset ANYSEARCH_KEY BOCHA_KEY

.venv/bin/python deploy.py --cn-provider anysearch   # or bocha; sets the interceptor's DST_TOOL
.venv/bin/python test_exposure.py                    # 8 cases
.venv/bin/python test_format.py                      # 6 cases
.venv/bin/python cleanup.py                          # deletes everything, see Cleanup
```

`deploy.py` creates a target only for providers whose key is stored. Tests read the
current route (`cn_provider`) from `state.json`.

## Targets and credentials

| target | endpoint | header injected by the Gateway |
|---|---|---|
| `websearch` | AgentCore Web Search connector | Gateway IAM role |
| `anysearch` | `https://api.anysearch.com/mcp` | `Authorization: Bearer <key>` (`credentialPrefix="Bearer "`) |
| `bocha` | `https://mcp.bochaai.com/mcp` | `Authorization: Bearer <key>` |

AnySearch's sample `X-Anysearch-Client` header is not required. For AnySearch and Bocha an
invalid key returns `isError: true`, so successful searches through the Gateway confirm the
stored key is used.

## Argument mapping

| WebSearch | AnySearch `search` | Bocha `bocha_web_search` |
|---|---|---|
| `query` | `query` | `query` |
| `maxResults` | `max_results` (clamped to 1-10) | `count` (clamped to 1-10) |
| - | - | - (`freshness` defaults to `noLimit`) |

## Unified result format

The RESPONSE stage rewrites each successful `tools/call` result (`lambdas/normalize.py`) into:

```json
{"provider": "agentcore-web-search | anysearch | bocha",
 "results": [{"title": "", "url": "", "publishedDate": "YYYY-MM-DD | null", "author": "str | null", "text": ""}]}
```

The envelope is reduced to `content` + `isError`. The RESPONSE stage sees the original
request (`websearch___WebSearch`) even after rerouting, so the provider is detected from the payload:

| provider | raw format | detected by |
|---|---|---|
| AgentCore Web Search | JSON | JSON with `results` |
| AnySearch | Markdown (`### N. Title`, `- **URL**:`, trailing ` date: Aug 14, 2026`) | starts with `## Search Results` |
| Bocha | text: `Title/URL/Description/Published date/Site name`, blank-line separated | starts with `Title:` |

## Findings (2026-11-18)

- The Gateway routes on the tool name rewritten by the REQUEST interceptor (not documented; verified by test).
- RESPONSE still runs after a REQUEST short-circuit (documented).
- Third-party targets bring extra tools (AnySearch `batch_search`/`extract`/`get_sub_domains`/`score`; Bocha `bocha_ai_search`); all hidden and rejected.

## End-to-end: AgentCore Managed Harness

`harness_demo.py` creates a managed agent and searches through this Gateway:

- Model `us.openai.gpt-6.1-terra` (Bedrock inference profile).
- Tool type `agentcore_gateway` with outbound auth `awsIam`, matching the Gateway's `AWS_IAM` inbound auth.
- Execution role `ic-reroute-poc-harness-role`: invoke this model, invoke this Gateway, write `/aws/bedrock-agentcore/*` logs.
- `memory={"disabled": {}}`: otherwise the Harness creates a managed memory and the role also needs
  access to it (e.g. `bedrock-agentcore:ListEvents`), or the first invocation fails.

```bash
.venv/bin/python harness_demo.py              # one Chinese and one English question
.venv/bin/python harness_demo.py "<question>" # custom question
```

Result (2026-11-18, Chinese route = AnySearch): the model called `websearch___WebSearch` both times.
"杭州西湖一年中什么时候去最好？" was routed to AnySearch (ly.com, trip.com, zhihu results);
"What are AgentCore Gateway interceptors used for?" stayed on AgentCore Web Search (AWS docs).
The prompt never mentions AnySearch.

## Limitations

- Text parsing depends on each provider's current format; unknown formats pass through unchanged.
- AnySearch relative dates ("2 days ago") become `null`; AnySearch's requested `score` feedback is not sent.
- Chinese queries leave AWS for a third-party provider; see [Third-party services](#third-party-services).
- Search results are untrusted input; see [Search results are untrusted input](#search-results-are-untrusted-input).
- The Harness's built-in `web_fetch` tool does not go through the Gateway. Restricting tools with `allowedTools`
  is unresolved: `websearch___WebSearch`, `search` and `search___*` all removed the Gateway tool as well.

## Cleanup

```bash
.venv/bin/python cleanup.py
```

Deletes the Harness (if `harness_demo.py` was run), every target on the Gateway, the Gateway, every API key
credential provider whose name starts with `ic-reroute-poc-`, the interceptor Lambda and its CloudWatch log
group (created by `deploy.py` with 14-day retention), the three IAM roles, and finally `state.json`. Log
groups the Harness may write under `/aws/bedrock-agentcore/*` are not deleted; remove them in the
CloudWatch console if you do not need them.

## Security

See [CONTRIBUTING](CONTRIBUTING.md#security-issue-notifications) for more information.

## License

This library is licensed under the MIT-0 License. See the [LICENSE](LICENSE) file.
