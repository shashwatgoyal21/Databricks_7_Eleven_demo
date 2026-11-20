# Next Best Offer app: AppKit data-screen design

Design for rebuilding `nbo-demo/app` (today Streamlit) as a custom-code Databricks App on AppKit (Node/TypeScript/React). Same four screens, same gold tables and metric view, same demo story. Component names below are checked against `npx @databricks/appkit docs` (appkit-ui API reference).

No Genie/chat surface is in the app (Genie stays in the AI/BI Genie space per the demo script), so the Genie trust section of the design skill does not apply.

---

## Direction

- **Frame:** The VP of Loyalty & Personalization and their marketers decide which promotions to run, who to send them to, and approve the send. Data refreshes when the build job runs (demo date 2026-09-30). Desktop, presented live on a call.
- **Genre:** Analytic, with a stratified layout on every page (message + KPIs on top, evidence below, action at the bottom).
- **Structure:** Hierarchical: Portfolio → Audience → Member, plus a Measurement page as the evidence base. Four `Tabs`, in the order of the demo walkthrough.
- **Design intent:** Every page title states its finding. Redemption rate is never shown without measured lift next to it. Every dollar figure says per send, per month, or per year.

## Pattern & notation choices

**Composition**
- Data information: aggregation and derived values (net margin per send, measured lift = treatment − holdout conversion). Each derivation is stated in a `Tooltip` on the column header or KPI label.
- Meta information: one freshness line under every page title: `Data as of 30 Sep 2026 · workspace.nbo_demo · refreshed <last_altered>`; synthetic-data disclaimer in the footer.
- Layout: stratified. KPI row (4 cards) → one primary chart → detail table → action.
- Interaction: filter-and-focus only where the user asks a real question (promotion, strategy, member). Row action in the portfolio table jumps to Audience with that promotion preselected.
- Color: one shared semantic scheme across all pages (below). No decorative color, no emojis in headers.

**Notation (IBCS)**
- **SAY:** titles carry the message, computed from data, e.g. *"Spend tripled since 1 Apr while incremental margin turned negative"*.
- **UNIFY:** one meaning per color everywhere:

| Meaning | Token | Used for |
|---|---|---|
| Actual / primary measure | `--foreground` (chart: `--chart-cat-1`) | Discount spend line, neutral bars |
| Comparison / baseline | `--muted-foreground` | Jan–Mar reference, holdout, non-highlighted tiers |
| Good (margin > 0, pays back) | `--success` (chart: positive end of `--chart-div-*`) | Positive net margin, "Run" badge |
| Bad (margin < 0, loses money) | `--destructive` (chart: negative end of `--chart-div-*`) | Negative net margin, "Retire" badge |
| Caution | `--warning` | "Redesign" badge, small-sample note |
| Highlight (the page's main message) | `--primary` | Coffee + Croissant / Persuadable emphasis |

- **Scenario marks:** the comparison here is policy period, not plan or prior year. Jan–Mar (curated) is the baseline: lighter solid. Apr–Sep (send-to-all) is actual: solid. The 1 Apr policy change is a vertical dashed reference line with a direct label.
- **CHECK:** zero baseline on every bar chart; one shared y-scale across the measurement small multiples; currency formatted with sign (`+$700`, `−$1,100`); rates in % and lift in pts, never mixed in one axis.
- **Higher is good?** Discount spend: no (up = bad). Incremental margin, net margin, measured lift: yes. KPI deltas follow this per metric.

---

## Component plan

All imports from `@databricks/appkit-ui/react`. Queries live in `config/queries/*.sql`; types in `shared/appkit-types/analytics.d.ts`. Queries are `*.obo.sql` (run as the signed-in user) so the `loyalty_region_filter` row filter and `loyalty_pii_mask` apply inside the app too. This needs the `sql` user API scope on the app. The approvals write stays on the service principal.

### App shell
- Header → `Card`-less bar: app name, `Badge` with the signed-in user (from `x-forwarded-email` via a `/api/whoami` route), `Badge variant="outline"` "Synthetic data".
- Navigation → `Tabs` / `TabsList` / `TabsTrigger` ×4: Portfolio, Audience, Member, Measurement.
- Freshness line → `<p class="text-muted-foreground text-sm">` fed by query `freshness.obo.sql`:
  ```sql
  SELECT (SELECT MAX(month_end) FROM workspace.nbo_demo.promo_monthly) AS data_as_of,
         (SELECT last_altered FROM workspace.information_schema.tables
           WHERE table_schema = 'nbo_demo' AND table_name = 'promo_portfolio') AS refreshed_at
  ```
- Toasts → `Toaster`.
- Shared helper `KpiCard` (composed, not an AppKit export): `Card` + `CardHeader` (label + `Tooltip` with definition) + `CardContent` (value, unit, period) + `CardFooter` (delta with `lucide-react` `ArrowUp`/`ArrowDown`, colored by the metric's good/bad direction).

### 1. Portfolio: "Is promo spend working?"
Title (computed): *"Spend up 3× since 1 Apr; incremental margin turned negative"*

| Element | Component | Data | States |
|---|---|---|---|
| KPI: Monthly discount spend, Apr–Sep vs Jan–Mar | `KpiCard` | `kpi_policy.obo.sql` on `metrics_promotions` grouped by `send_policy` | `Skeleton` ×4 while loading |
| KPI: Monthly incremental margin (vs 10% holdout) | `KpiCard`, value colored by sign | same query | |
| KPI: Coffee + Croissant redemptions that would happen anyway | `KpiCard`, subline "38% redemption rate" | `kpi_hero.obo.sql` | |
| KPI: Annual margin gain from uplift targeting | `KpiCard` | `kpi_gain.obo.sql` (`SUM(annual_gain_vs_blast)`) | |
| Spend vs incremental margin by month | `LineChart queryKey="spend_margin_trend" xKey="month_end" yKey={["discount_spend","incremental_margin"]} smooth={false} showSymbol` + `options` for a `markLine` at 1 Apr (dashed, label "1 Apr: send to all eligible") and a zero line. `valueFormatter` → `$` | `spend_margin_trend.obo.sql` (one row per month, two columns) | `Skeleton h-[280px]`; `Alert variant="destructive"` on error |
| Promotion opportunity ranking | `Table` (not `DataTable`: its auto-format abbreviates margins and would show `incremental_margin` without `$`) from `useAnalyticsQuery("portfolio")`. Columns: Rank, Promotion, Eligible, Redemption rate, Measured lift (pts), Net margin/send all eligible, Net margin/send targeted, Annual opportunity, Recommendation `Badge` (Run / Redesign / Retire). Signed values colored `text-success` / `text-destructive`. Row action `Button variant="ghost"` "Target audience →" | `portfolio.obo.sql` (5 rows) | `Empty` "No promotions visible for your region" if row filter returns nothing |
| Takeaway | `Alert` (default variant) with the computed sentence from the current app | from `portfolio` row 1 | hidden while loading |

### 2. Audience: "Who does this offer actually move?"
Title (computed): *"Uplift targeting turns Coffee + Croissant from −$1,100 to +$700 per send"*; for Late-Night Energy: *"No audience pays back at a $1 discount"*.

| Element | Component | Data | States |
|---|---|---|---|
| Promotion picker | `Select` (options from `portfolio`) | URL search param so the portfolio row action can preselect | |
| Strategy | `ToggleGroup type="single"`: Uplift (recommended) · Propensity (same size) · All eligible | client state | |
| KPIs: Targeted audience, Expected redemptions (+ "% would buy anyway"), Discount cost/send, Net incremental margin/send | `KpiCard` ×4 | `strategy_summary.obo.sql` with `promotion_id: sql.string(...)`: all three strategies in one query, aggregated in the warehouse (see below) | `Skeleton` |
| Strategy comparison (one send) | `BarChart orientation="horizontal" data={summary} xKey="strategy" yKey="net_margin"` with per-bar color from `options` (positive/negative end of the diverging palette) and `selected={strategy}` to emphasize the chosen strategy. Zero baseline visible | same query | |
| Audience uplift breakdown | `Table`: Tier, Members, Buys without offer, Buys with offer, Lift (pts), Net margin/send, Action `Badge`. Persuadable row emphasized (`bg-muted`) | `audience_tiers.obo.sql` with `promotion_id` | `Empty` if no tiers |
| Outcome | `Alert` (default) when net margin > 0; `Alert` with `--warning` styling + "Redesign or retire" when no tier pays back | derived | |
| Approve | `Select` channel + `Button` "Approve: N members" → `AlertDialog` confirm (shows promotion, strategy, audience, expected net margin, channel) → POST `/api/approvals` → `Toaster` success/error. Disabled when audience = 0 or net margin ≤ 0 | custom plugin route; inserts into `campaign_approvals` as service principal with `approved_by` = `x-forwarded-email` | Button shows `Spinner` while posting; error toast on failure, never silent |
| Recent approvals | `DataTable queryKey="approvals" parameters={{}} pageSize={10}` | `approvals.sql` (`ORDER BY approved_at DESC`) | built-in loading/empty/error; `labels` set to "No approvals yet" |

`strategy_summary.obo.sql` (replaces pulling ~25K score rows into the client):
```sql
WITH s AS (
  SELECT *, ROW_NUMBER() OVER (ORDER BY p_with_offer DESC) AS prop_rank
  FROM workspace.nbo_demo.member_offer_scores
  WHERE promotion_id = :promotion_id AND eligible),
n AS (SELECT COUNT_IF(tier = 'Persuadable') AS k FROM s),
p AS (SELECT discount_cost FROM workspace.nbo_demo.promotions WHERE promotion_id = :promotion_id)
SELECT 'Uplift' AS strategy, 1 AS ord, * FROM (
  SELECT COUNT(*) audience, SUM(p_with_offer) redemptions, SUM(p_without_offer) anyway,
         SUM(p_with_offer) * (SELECT discount_cost FROM p) discount_cost, SUM(expected_net_margin) net_margin
  FROM s WHERE tier = 'Persuadable')
UNION ALL
SELECT 'Propensity', 2, * FROM (
  SELECT COUNT(*), SUM(p_with_offer), SUM(p_without_offer),
         SUM(p_with_offer) * (SELECT discount_cost FROM p), SUM(expected_net_margin)
  FROM s WHERE prop_rank <= (SELECT k FROM n))
UNION ALL
SELECT 'All eligible', 3, * FROM (
  SELECT COUNT(*), SUM(p_with_offer), SUM(p_without_offer),
         SUM(p_with_offer) * (SELECT discount_cost FROM p), SUM(expected_net_margin)
  FROM s)
ORDER BY ord
```
This reproduces `strategy_summary()` in the current `app.py` exactly (same audience rules, `SUM(expected_net_margin)` for net margin, redemptions × discount cost).

### 3. Member: "Why this shopper gets this offer"
Title (computed): *"Kevin gets Coffee + Croissant: it moves him from 6% to 31%"* / *"Hannah gets no offer: she already buys the pastry"*

| Element | Component | Data | States |
|---|---|---|---|
| Featured shopper | `Select` | `featured_members.obo.sql` | |
| Member ID lookup | `InputGroup` (`Input inputMode="numeric"` + `Button` "Look up"); invalid input → inline `Field` error text | `member_profile.obo.sql` with `member_id: sql.number(...)` | `Empty` "No member 7110000042 in your region" when the row filter or a wrong ID returns nothing |
| Profile KPIs: CRM segment, Visits/active week, Avg basket, Last visit | `KpiCard` ×4 (no deltas) | `member_profile` | `Skeleton` |
| Behavioral signals | `Card` + `Item` list (4 rows: identity/region/tenure, coffee + pastry rates, visit mix, visits/app/opt-in). Name shown masked (`***`) when the viewer lacks `loyalty_pii` | `member_profile` | |
| Recommended action | `Card` with promotion name, channel, expected net margin (`text-success`), and "Why this offer won" text from `reason`. No-offer case: `Card` + `Badge variant="secondary"` "Hold back" + reason | `member_scores.obo.sql` | |
| Promotion scoring breakdown | `Table`: Promotion, Buys with offer (`Progress` 0–100 inside the cell + value), Buys without, Lift (pts), Net margin, Decision `Badge` (Recommended / Suppress · tier / Ineligible / Fallback). Ineligible rows `text-muted-foreground`, values "—" | `member_scores.obo.sql` (≤5 rows) | |

### 4. Measurement: "The model's tiers hold up against the holdout"
Title (computed): *"Persuadables show +22 pts measured lift; Sure Things show ~0"*

| Element | Component | Data | States |
|---|---|---|---|
| Measured lift by tier, per promotion | Small multiples: 5 × `BarChart xKey="tier" yKey="measured_uplift"` in a CSS grid, one per promotion, `selected="Persuadable"` (single highlight), one shared y-range via `options.yAxis = {min, max}` computed across all rows, `valueFormatter` → `+0.0 pts`. Tier order fixed: Persuadable, Low ROI, Sure Thing, Lost Cause | `tier_backtest.obo.sql` (`holdout_sends >= 30`) | Note under the grid: "Tiers with fewer than 30 holdout sends are hidden." |
| Keyboard/exact alternative | `Collapsible` "Show as table" → `Table` with treatment and holdout sends | same query | |
| Monthly results by promotion | `Table` in `ScrollArea` (45 rows): Month, Promotion, Sends, Holdout, Redemption rate, Measured lift (pts), Discount spend, Incremental margin (signed, colored). Apr–Sep rows separated from Jan–Mar by a labeled `Separator` row "1 Apr: send to all eligible" | `monthly_results.obo.sql` (aggregated in SQL) | `Empty`, `Alert` |

### Required states (every view)
- Loading → `Skeleton` sized to the final element (KPI 96px, charts at their `height`).
- Empty → `Empty` with the next action ("Pick another promotion", "Check the member ID", "Ask an admin to add you to a marketing region group").
- Error → `Alert variant="destructive"` with the message from `useAnalyticsQuery().error` and a `Button` "Retry". Never a blank panel.
- Warehouse cold start → use `warehouseStatus` from `useAnalyticsQuery` to show "Starting SQL warehouse…" in place of the skeleton text.
- Partial → if some promotions are hidden by the row filter, a muted note "Showing N of 5 promotions for your region".

---

## Tradeoffs & risks

- **Summarized:** member-level scores are aggregated in the warehouse; the client never holds the 25K-row score table. Member detail is fetched one member at a time.
- **Hidden behind interaction:** the measurement data table (behind `Collapsible`), metric definitions (behind `Tooltip`). The headline numbers and the redemption-vs-lift comparison stay visible without interaction.
- **OBO:** switching queries to `*.obo.sql` makes the Texas-only and `***` governance moments work inside the app, not just in the dashboard and Genie. It also means each viewer must have `SELECT` on `workspace.nbo_demo` and be in a region or leadership group, or they see `Empty` states. Keep a `.sql` (service principal) fallback for the demo presenter if needed.
- **Chart colors:** ECharts draws on canvas and cannot read `var()` or `oklch()`. Read the resolved `--chart-div-*` / `--chart-cat-*` values (held as hex/rgb per the AppKit docs) with `getComputedStyle` in one small `useChartColors()` hook, and pass them through `options`. Override the variables for both light and dark mode if you change them.
- **Small multiples width:** 5 charts side by side need ~1100px; wrap to 3 + 2 below that.
- **Scope:** no new pages, filters, or personalization beyond what the demo walkthrough uses.

## Mapping from the current Streamlit app

| Streamlit today | AppKit |
|---|---|
| `st.metric` | `KpiCard` (composed from `Card`) with tooltip definition and freshness |
| Altair line + rule + text | `LineChart` + `options.markLine` |
| Altair faceted bar | 5 × `BarChart` with shared y-range, `selected` highlight |
| `st.dataframe` | `Table` (exact formatting) or `DataTable` (approvals) |
| `st.selectbox` / `st.radio` | `Select` / `ToggleGroup` |
| `st.button` + `st.toast` | `Button` → `AlertDialog` → `Toaster` |
| `st.info` / `st.success` / `st.warning` | `Alert` |
| Hex colors `#FF6600`, `#008060`, `#C0392B`, `#9AA5A8` | Semantic tokens in the table above |
| `SELECT *` of whole tables into pandas | Parameterized `*.obo.sql` queries with `sql.string()` / `sql.number()` |
| `data.approve()` SQL insert | Custom plugin route `POST /api/approvals` |
| Sidebar "Signed in as" | Header `Badge` from `/api/whoami` |

## Query files

```
config/queries/
  freshness.obo.sql
  kpi_policy.obo.sql          -- metrics_promotions by send_policy
  kpi_hero.obo.sql            -- PR01 redemption rate + would-happen-anyway
  kpi_gain.obo.sql
  spend_margin_trend.obo.sql  -- month_end, discount_spend, incremental_margin
  portfolio.obo.sql           -- promo_portfolio
  strategy_summary.obo.sql    -- :promotion_id
  audience_tiers.obo.sql      -- :promotion_id
  approvals.sql               -- campaign_approvals, last 20
  featured_members.obo.sql
  member_profile.obo.sql      -- :member_id
  member_scores.obo.sql       -- :member_id, joined to promotions
  tier_backtest.obo.sql
  monthly_results.obo.sql
```
