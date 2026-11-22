Picture a sales director typing into the new AI data assistant on a Monday morning: "What was revenue last month?" A number comes back in four seconds. $8,550. Clean, confident, no caveats. She pastes it into a deck for the 10 AM leadership call.

Finance's number for the same month is $5,550.

Nobody wrote bad SQL. The agent's query ran. It joined nothing it shouldn't have, and it didn't make up a table. It picked one reasonable reading of "revenue last month" out of at least five, and it didn't tell anyone it had picked. In the fixture below, those five readings range from $5,550 to $8,550, a 54% spread on a ten-row table.

That's the failure I think BAs should be writing requirements for right now. A text-to-SQL agent rarely fails by writing broken SQL. It fails by writing correct SQL for a question nobody asked. So in this post I'll give you a spec for **answer receipts**: what the agent has to return next to every number, when it has to stop and ask, and how you test it. There's a runnable SQLite fixture, a filled receipt, and the acceptance criteria I'd hand to the team building it.

**Prefer to watch?** The receipts idea started for me with AI-written user stories, where every story has to quote the meeting it came from. Same principle, different artifact:

{% embed https://www.youtube.com/watch?v=cXMIEbvokcc %}

*Video: [How to Write User Stories with AI (Without Made-Up Requirements)](https://www.youtube.com/watch?v=cXMIEbvokcc), my 6-minute walkthrough of the receipts method for stories.*

## Credit where it's due

The phrase "answer receipt" isn't mine. It comes from a post by AI Explore on Dev.to last week, [Text-to-SQL Agents Answer Questions Nobody Reviewed. Add Receipts](https://dev.to/aiexplore369zoho/text-to-sql-agents-answer-questions-nobody-reviewed-add-receipts-123h). The core argument: a dashboard is a question somebody reviewed, while a text-to-SQL answer is a question nobody reviewed, so the agent should return "a structured record of the choices it made" instead of a bare number. The post lists what goes on it (the metric and its definition by identifier, grain, filters, time range, timezone, any defaults the user never specified, the SQL, row counts at key stages) and gives a rule for when to ask: generate several plausible interpretations, run them, and only ask the user when the results diverge enough that "the ambiguity is material."

It also has the line I keep coming back to: an agent that's right 90% of the time and hides which 10% is worse than one that's right 80% of the time and tells you where to look.

What I want to add is the BA layer. That post is written for the engineer building the agent. This one is for the person who has to write the acceptance criteria, pick the tolerance, and sign the thing off. Those are different jobs, and the second one is where most of these projects go quiet.

## Why now

Three things make this a this-quarter problem rather than a someday problem.

First, the tools are shipping. Power BI's Copilot now supports [verified answers](https://learn.microsoft.com/power-bi/create-reports/copilot-prepare-data-ai-verified-answers): "human-approved, visual responses in Copilot that predefined phrases trigger." Microsoft's page (updated 10 September 2026) allows up to 250 per semantic model and 15 trigger phrases each. Snowflake's Cortex Analyst has a [Verified Query Repository](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst/verified-query-repository): "a collection of questions and corresponding SQL queries to answer them," with optional `verified_by` and `verified_at` fields. Both vendors have arrived at the same idea. Reviewed answers get special treatment. Everything else is improvised.

Second, the improvised part is still weak on real schemas. The [BEAVER benchmark](https://arxiv.org/abs/2409.02038) from MIT and others is built from real private data warehouses: 9,128 question-SQL pairs over 812 tables, with an average of 101.5 tables and 869.4 columns per database. In its latest version (v3, 13 May 2026) the authors report that "state-of-the-art agentic frameworks using the advanced model GPT-5.2 achieve only 10.8% accuracy," rising to 30.1% when given oracle hints for every subtask. That's on enterprise schemas, not the tidy academic ones where the same models look great.

Third, the people doing the work are already saying it. Hilal Ud Din's October post on IIBA's Analyst Catalyst blog, [Where AI Helps My Business Analysis Work (And Where I Draw the Line)](https://www.iiba.org/business-analysis-blogs/where-ai-helps-my-business-analysis-work-and-where-i-draw-the-line/), puts it in one sentence: "A confident wrong number is worse than no number."

So the question isn't whether your company will get a text-to-SQL agent. It's whether anyone writes down what it has to show its work on.

## The fixture: one question, five honest answers

Here's the setup, on fictional Northstar Systems data. Ten orders, three refunds. The user is in New York and asks on 16 November 2026: "What was revenue last month?"

Two edge rows matter. Order 1001 was placed at 02:30 UTC on 1 October, which is 10:30 PM on 30 September in New York. Order 1009 was placed at 01:40 UTC on 1 November, which is 9:40 PM on 31 October in New York. (US daylight saving time ends at 2 AM on 1 November 2026, so New York's October runs from 04:00 UTC on 1 October to 04:00 UTC on 1 November.) There's also a refund on 2 October for a September order.

```python
import sqlite3
db = sqlite3.connect(":memory:")
db.executescript("""
CREATE TABLE orders (order_id INTEGER PRIMARY KEY, customer_id INTEGER,
                     created_at_utc TEXT, status TEXT, amount REAL);
CREATE TABLE refunds (refund_id INTEGER PRIMARY KEY, order_id INTEGER,
                      refunded_at_utc TEXT, amount REAL);
INSERT INTO orders VALUES
 (1001, 7, '2026-10-01 02:30:00', 'shipped',   1200.00),  -- 30 Sep 22:30 in New York
 (1002, 8, '2026-10-03 15:00:00', 'shipped',    850.00),
 (1003, 9, '2026-10-09 18:20:00', 'refunded',   400.00),
 (1004, 7, '2026-10-14 13:05:00', 'shipped',   2300.00),
 (1005, 10,'2026-10-18 20:45:00', 'cancelled',  600.00),
 (1006, 11,'2026-10-22 11:10:00', 'shipped',   1750.00),
 (1007, 12,'2026-10-27 16:00:00', 'pending',    950.00),
 (1008, 8, '2026-10-30 21:15:00', 'shipped',    500.00),
 (1009, 13,'2026-11-01 01:40:00', 'shipped',   1100.00),  -- 31 Oct 21:40 in New York
 (1010, 14,'2026-09-29 14:00:00', 'shipped',    700.00);
INSERT INTO refunds VALUES
 (1, 1003, '2026-10-12 10:00:00', 400.00),
 (2, 1006, '2026-10-25 09:30:00', 250.00),
 (3, 1010, '2026-10-02 12:00:00', 700.00);
""")

UTC_OCT = "'2026-10-01' AND created_at_utc < '2026-11-01'"
NY_OCT  = "'2026-10-01 04:00:00' AND created_at_utc < '2026-11-01 04:00:00'"
OK = "status IN ('shipped','refunded')"

readings = {
 "A gross, UTC month, all statuses":
   f"SELECT SUM(amount) FROM orders WHERE created_at_utc >= {UTC_OCT}",
 "B gross, UTC month, shipped+refunded":
   f"SELECT SUM(amount) FROM orders WHERE {OK} AND created_at_utc >= {UTC_OCT}",
 "C net of refunds in month, UTC month":
   f"""SELECT (SELECT SUM(amount) FROM orders WHERE {OK} AND created_at_utc >= {UTC_OCT})
      - (SELECT COALESCE(SUM(amount),0) FROM refunds
         WHERE refunded_at_utc >= '2026-10-01' AND refunded_at_utc < '2026-11-01')""",
 "D net of refunds in month, New York month":
   f"""SELECT (SELECT SUM(amount) FROM orders WHERE {OK} AND created_at_utc >= {NY_OCT})
      - (SELECT COALESCE(SUM(amount),0) FROM refunds
         WHERE refunded_at_utc >= '2026-10-01 04:00:00' AND refunded_at_utc < '2026-11-01 04:00:00')""",
 "E net, refunds tied to the order's month, New York":
   f"""SELECT SUM(o.amount) - COALESCE(SUM(r.amount),0)
       FROM orders o LEFT JOIN refunds r ON r.order_id = o.order_id
       WHERE o.{OK} AND o.created_at_utc >= {NY_OCT.replace('created_at_utc','o.created_at_utc')}""",
}
results = {k: db.execute(q).fetchone()[0] for k, q in readings.items()}
for k, v in results.items():
    print(f"{k:52} {v:>10,.2f}")
lo, hi = min(results.values()), max(results.values())
print(f"spread vs lowest: {(hi - lo) / lo:.1%}")
```

Output when I ran it:

```text
A gross, UTC month, all statuses                       8,550.00
B gross, UTC month, shipped+refunded                   7,000.00
C net of refunds in month, UTC month                   5,650.00
D net of refunds in month, New York month              5,550.00
E net, refunds tied to the order's month, New York     6,250.00
spread vs lowest: 54.1%
```

Every one of those queries is valid SQL. Every one answers a question a reasonable person might mean by "revenue last month." A grader that only checks "did the query run and return a number" would pass all five.

### The row I didn't expect

Look at C and D. They differ by only $100, and that's the dangerous part. The timezone choice moves two orders in opposite directions: order 1001 ($1,200) drops out of October in New York, and order 1009 ($1,100) drops in. The two errors nearly cancel. If you tested the agent by comparing its UTC answer to finance's New York answer on this one month, you'd see a 1.8% gap and call it rounding.

Next month the edge orders won't line up so neatly. That's why a single matching total is weak evidence, and why I'd always put row counts on the receipt. D counts 6 eligible orders. C counts 6 too, but they're a different 6. Same count, same-ish total, different rows. Only an order-ID-level comparison catches it.

### Which one is right?

None of them, until somebody decides. That's the point. For Northstar, say finance books refunds in the month they happen and reports in New York time. That's reading D, $5,550. The agent's first instinct, A, is $3,000 too high because it counted a cancelled and a pending order and ignored refunds.

![A star schema: one fact table in the middle with dimension tables around it](https://upload.wikimedia.org/wikipedia/commons/b/bb/Star-schema.png)
*A star schema answers "what's the grain?" by design: one fact table, one row per event. A text-to-SQL agent working on raw tables has to guess the grain, the statuses and the time zone every time. Image: ["Star-schema.png"](https://commons.wikimedia.org/wiki/File:Star-schema.png) by SqlPac, [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/), via Wikimedia Commons.*

## The receipt spec

Here's what I'd require next to every number the agent returns. I've written it as a JSON shape because that's what the engineers will build, but each field is really a business rule.

```json
{
  "answer": 5550.00,
  "unit": "USD",
  "question_as_asked": "What was revenue last month?",
  "metric": {
    "id": "net_revenue",
    "version": "v2",
    "status": "certified",
    "definition": "Shipped or refunded order amounts minus refunds issued in the period",
    "certified_by": "Finance reporting lead",
    "certified_on": "2026-10-05"
  },
  "grain": "one row = one order",
  "period": {
    "label": "October 2026",
    "timezone": "America/New_York",
    "utc_start": "2026-10-01T04:00:00Z",
    "utc_end_exclusive": "2026-11-01T04:00:00Z",
    "how_chosen": "default: user's profile timezone"
  },
  "filters": [
    {"field": "orders.status", "rule": "IN ('shipped','refunded')", "source": "metric definition"}
  ],
  "defaults_applied": [
    "'last month' = previous calendar month in the user's timezone",
    "refunds counted in the month issued, not the order's month"
  ],
  "row_counts": {
    "orders_in_period_any_status": 8,
    "orders_after_status_filter": 6,
    "refunds_in_period": 3
  },
  "interpretations_checked": 5,
  "interpretation_spread": "54.1% (resolved by certified metric)",
  "sql": "SELECT ... (full text)",
  "data_freshness": "orders loaded 2026-11-16 06:10 ET",
  "answer_type": "certified"
}
```

Four fields do most of the work.

**`metric.status`.** Either `certified` (a person signed off this definition, like a Power BI verified answer or a Snowflake verified query) or `improvised` (the agent built it on the fly). The user interface must show the difference. AI Explore's post makes the same point: users need to tell certified answers from improvised ones. I'd go further and make it the first thing on screen.

**`defaults_applied`.** Every choice the user didn't make and the agent did. This is the field I'd fight hardest for, because it's the one that turns a silent guess into a visible one. If the list is empty on a question like "revenue last month," the agent is either lying or the metric definition is unusually complete.

**`row_counts`.** At least one count before filters and one after. A total with no count can't be compared to anything. Two counts let a finance analyst check the answer against their own system in a minute. (A reader called ontomato put it well in [a reply on Dev.to](https://dev.to/ontomato/comment/3khh3): two numbers end the argument faster than another meeting.)

**`interpretations_checked` and `interpretation_spread`.** Proof that the agent looked for other readings, and how far apart they landed. This is what drives the ask-or-answer decision below.

![A printed shop receipt](https://upload.wikimedia.org/wikipedia/commons/2/25/Receipt.jpg)
*A till receipt lists what you were charged for, line by line, so you can check it before you leave the shop. That's the bar for an AI data answer too. Image: ["Receipt.jpg"](https://commons.wikimedia.org/wiki/File:Receipt.jpg) by Deavmi, [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/), via Wikimedia Commons.*

## When the agent must stop and ask

Here's my take, and I expect some people to disagree with it: **the agent should not ask clarifying questions because it feels unsure.** Model confidence is a bad trigger. It asks too often on easy questions and not at all on the ones that look easy and aren't, like "revenue last month."

The trigger should be the spread. Run the plausible interpretations. If they all land within tolerance, answer and show the receipt. If they don't, ask, and ask about the specific fork that moved the number.

And the tolerance isn't a model setting. It's a business requirement with an owner. Here's the decision table I'd put in the spec, first match wins:

| # | Condition | Agent does | Receipt shows |
|---|---|---|---|
| 1 | A certified metric matches the question | Answer with the certified definition | `answer_type: certified`, definition version, who certified it |
| 2 | No certified metric; all interpretations within tolerance (Northstar: 1% for finance metrics, 5% for operational counts) | Answer with the most common reading | `answer_type: improvised`, every default applied, the spread |
| 3 | No certified metric; spread above tolerance; the forks are known (status set, refund timing, timezone) | Ask one question that names the fork and shows the numbers ("Gross: $7,000. Net of refunds: $5,550. Which do you mean?") | The options and their values |
| 4 | Spread above tolerance and the agent can't name the fork | Don't answer. Route to the data team | The interpretations it tried and why it stopped |
| 5 | The question touches a metric on the "certified only" list (revenue, margin, headcount) and rule 1 didn't match | Don't improvise. Say the metric isn't certified for this question and who to ask | The metric's owner |

Rule 5 is the one teams push back on, because it makes the agent answer fewer questions in month one. I'd still ship it. For a small set of numbers that end up in board decks, an agent that says "I can't answer that one yet" is doing its job. Every refusal there is also a free backlog item: the questions people ask that have no certified answer are exactly the ones your data team should certify next.

## Acceptance criteria you can hand to the team

Written in the Given/When/Then style from my [acceptance criteria template](https://github.com/prachitparikh/ba-toolkit/blob/main/templates/acceptance-criteria-template.md), using the fixture above as the test data.

```gherkin
Feature: Answer receipts for the data assistant

  Scenario: Certified metric answers with its definition
    Given the metric "net_revenue" v2 is certified by the finance reporting lead
    And the Northstar October fixture is loaded
    When a user in America/New_York asks "What was revenue last month?" on 2026-11-16
    Then the answer is 5550.00 USD
    And the receipt shows answer_type "certified", metric id "net_revenue" and version "v2"
    And the receipt shows the period in America/New_York with UTC bounds 2026-10-01T04:00Z to 2026-11-01T04:00Z
    And the receipt shows 8 orders before the status filter and 6 after

  Scenario: Material ambiguity triggers one specific question
    Given "net_revenue" is NOT certified
    And the tolerance for finance metrics is 1%
    When the same user asks the same question
    Then the agent does not return a single number
    And it asks one question naming the refund treatment, showing 7,000.00 and 5,550.00

  Scenario: Certified-only metric is never improvised
    Given "gross_margin" is on the certified-only list and has no certified definition
    When a user asks "What was gross margin last month?"
    Then the agent returns no number
    And it names the metric owner to contact

  Scenario: Offsetting edge rows are caught at row level
    Given the agent's answer and finance's answer are within 2% in total
    When the UAT check compares order IDs behind both answers
    Then any order ID present in one and not the other is listed as a defect
```

The last scenario is the C-versus-D trap written as a test. A total-only check would pass it. An order-ID check doesn't.

## How I'd test the receipts themselves

Receipts can lie too. An agent can write `"timezone": "America/New_York"` and run the query in UTC. So the checks have to compare the receipt to what actually happened, not to itself.

1. **Re-run the receipt's SQL** outside the agent and confirm the same number. If they differ, the receipt isn't describing the query that produced the answer.
2. **Re-derive the period bounds** from the stated timezone and compare to the UTC bounds in the receipt. Do this on a daylight-saving month on purpose. November is perfect.
3. **Recount the rows** at each stage and compare to `row_counts`.
4. **Plant a cancelled order** in the fixture and check the receipt's status filter excludes it, and the count drops by one.
5. **Ask the same question three times.** The answer can stay the same while `defaults_applied` changes, and that's a stability defect even if the number didn't move.
6. **Check `certified` against the source of truth.** The certified list lives in the semantic model or verified-query repository, not in the agent's memory. A receipt that says certified for a metric that isn't in the repository is a severity-one defect.

How many runs is enough for that last kind of check? That's a separate question, and I wrote it up separately: [zero failures in 20 runs isn't a pass](https://prachitparikh.hashnode.dev/ai-uat-sample-size).

## What this doesn't solve

- **It doesn't make a wrong certified metric right.** If finance's v2 definition is wrong, every certified answer is wrong with a nice receipt attached. Certification moves the risk to a person, which is where it belongs, but it doesn't remove it.
- **The interpretation list can miss the real fork.** The agent can only compare the readings it thinks of. Northstar's fixture has five. A real warehouse with 869 columns, as BEAVER describes, has more forks than anyone will enumerate. That's why rule 4 exists.
- **Receipts add latency and screen space.** Users will ignore a 30-line receipt. Show three things up front (certified or not, period with timezone, row count) and the rest behind a click.
- **I haven't benchmarked an agent here.** This is a spec and a fixture, not a measurement of any product. The numbers above are from my SQLite run on fictional data.

## What I'd do on Monday

If a text-to-SQL or "ask your data" pilot is on your roadmap, here's the order I'd work in.

1. **Pick the five questions that end up in decks.** Revenue, margin, active customers, churn, headcount, whatever yours are. Put them on a certified-only list.
2. **Write each as a definition with a grain sentence** ("one row = one order"), eligible statuses, the timezone, and what an empty period returns. My post on [metric view relationships](https://prachitparikh.github.io/blog/metric-view-relationships.html) has the same discipline for semantic layers.
3. **Load them as certified answers** in whatever your tool supports: verified answers in Power BI, a verified query repository in Snowflake, a named metric in your semantic layer.
4. **Build a fixture like the one above** for each, with at least one edge row per fork (a cancelled order, a refund across the month boundary, an order near midnight UTC).
5. **Write the tolerance per metric family** and get the owner's name next to it.
6. **Add the receipt fields to the acceptance criteria** before the first sprint, not after the first wrong number in a deck.
7. **Profile the source tables first.** The forks come from the data. My [SQL data profiling](https://prachitparikh.hashnode.dev/sql-data-profiling) queries are where I'd start finding them.

And if the agent is also writing the SQL that the receipts describe, [review it like any other code](https://dev.to/prachitparikh/review-ai-generated-sql-before-you-trust-the-number-a-checklist-with-a-runnable-fixture-2j45) against a fixture with a known answer. The receipt tells you what it did. The review tells you whether that was right.

## Over to you

- If your team has a text-to-SQL or Copilot pilot running, does the user see whether an answer was certified or improvised?
- Who should own the tolerance: the data team, finance, or the person asking?
- Would you ship rule 5 (certified-only metrics) in month one, knowing the agent will say "I can't answer that" a lot?

I'd especially like to hear from anyone who's put verified answers or a verified query repository into production. Which questions did you certify first? Drop it in the comments.

## References

- AI Explore, [Text-to-SQL Agents Answer Questions Nobody Reviewed. Add Receipts](https://dev.to/aiexplore369zoho/text-to-sql-agents-answer-questions-nobody-reviewed-add-receipts-123h), Dev.to, 13 November 2026.
- Microsoft Learn, [Prepare your data for AI: Verified answers](https://learn.microsoft.com/power-bi/create-reports/copilot-prepare-data-ai-verified-answers), last updated 10 September 2026.
- Snowflake Documentation, [Cortex Analyst Verified Query Repository](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst/verified-query-repository).
- Peter Baile Chen, Devin Yang, Weiyue Li, Fabian Wenz, Yi Zhang, Nesime Tatbul, Michael Cafarella, Çağatay Demiralp, Michael Stonebraker, [BEAVER: An Enterprise Benchmark for Text-to-SQL](https://arxiv.org/abs/2409.02038), arXiv, v3, 13 May 2026.
- Hilal Ud Din, [Where AI Helps My Business Analysis Work (And Where I Draw the Line)](https://www.iiba.org/business-analysis-blogs/where-ai-helps-my-business-analysis-work-and-where-i-draw-the-line/), IIBA Analyst Catalyst blog, 20 October 2026.
- Atlan, [Text-to-SQL with AI: How It Works and Where It Breaks](https://atlan.com/know/ai-agent/data-for-ai/text-to-sql-with-ai/), 19 August 2026 (a vendor page; used here only for its description of failure modes).

## About me

I'm Prachit Parikh, a business analyst. I turn what stakeholders ask for into requirements a team can test, check the data with SQL, and see changes through UAT. I keep free templates, including [the receipts method for AI-written user stories](https://github.com/prachitparikh/ba-toolkit/blob/main/templates/meeting-notes-to-user-stories-receipts.md) and seven SQL validation checks, in my [BA Toolkit](https://github.com/prachitparikh/ba-toolkit) on [GitHub](https://github.com/prachitparikh), and I make short animated explainers on [YouTube](https://www.youtube.com/@PrachitParikh1). Besides Dev.to, I write on [Substack](https://prachitparikh.substack.com), [Medium](https://medium.com/@prachit.parikh), [Hashnode](https://prachitparikh.hashnode.dev), [Blogger](https://prachitparikh-ba.blogspot.com) and [WordPress](https://prachitparikhblog.wordpress.com), and I answer questions on [Quora](https://www.quora.com/profile/Prachit-Parikh-2). You can also find me on [LinkedIn](https://www.linkedin.com/in/prachitp), [Bluesky](https://bsky.app/profile/prachitparikh.bsky.social), [Kaggle](https://www.kaggle.com/prachitparikh), [Credly](https://www.credly.com/users/prachit-parikh), [Crunchbase](https://www.crunchbase.com/person/prachit-parikh-ct) and [Gravatar](https://gravatar.com/prachitparikhba). Everything is collected on [my website](https://prachitparikh.github.io/), [my portfolio](https://prachitparikh.github.io/portfolio.html) and [my profile hub](https://sites.google.com/view/prachit-parikh).
