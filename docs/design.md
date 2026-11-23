# Cloud Frugality Design Specification

## 1. Budget & Days Available Tracking

Cloud Frugality supports two distinct budget tracking models configured via the `/settings` interface:

### Option 1: Fixed Budget with Calendar Expiry
- **Purpose**: Tracks fixed credit grants, grant funds, or fixed-sum allowances with a firm expiration date.
- **Parameters**:
  - `fixed_budget_amount`: Total budget in USD (e.g., `$1000.00`).
  - `fixed_budget_expiry`: Expiration date in ISO 8601 format (`YYYY-MM-DD`).
- **Calculated Metrics**:
  - `days_available`: Calendar days remaining between UTC today and the expiration date:
    $$\text{days\_available} = \max(0, \text{expiry\_date} - \text{today})$$
  - `remaining_usd`: Total budget minus cumulative gross consumption to date:
    $$\text{remaining\_usd} = \max(0.0, \text{budgeted} - \text{window\_gross})$$
  - `days_until_exhaustion`:
    $$\text{days\_until\_exhaustion} = \left\lfloor \frac{\text{remaining\_usd}}{\text{avg\_daily\_gross}} \right\rfloor$$
  - `binding_limit`: Compares calendar expiry vs. burn exhaustion. If exhaustion occurs before the expiration date, exhaustion binds; otherwise calendar expiration binds.

### Option 2: Monthly Credits (Resets Every Month)
- **Purpose**: Models recurrent monthly promotional credits or recurring monthly spending limits.
- **Parameters**:
  - `monthly_credit_amount`: Monthly allowance in USD (e.g., `$200.00`).
  - `monthly_reset_day`: Calendar day of the month when credits refresh (1–31).
- **Calculated Metrics**:
  - `days_available`: Calendar days remaining in the current billing cycle until the upcoming reset date.
  - `remaining_usd`: Current monthly allowance minus consumption incurred during the active monthly cycle.

---

## 2. Daily Cost Baseline & Status Threshold Coloring

Cloud Frugality monitors daily consumption against an adjustable baseline:
- **Default Baseline**: `$0.70` USD/day (configurable in `/settings`).
- **Threshold Rules**:
  1. **RED (`cost-red`)**: Day spend strictly exceeds baseline ($>\$0.70$). Indicates budget overrun or resource leak.
  2. **YELLOW (`cost-yellow`)**: Day spend is $\ge 70\%$ of baseline up to $100\%$ ($\$0.49 \le \text{spend} \le \$0.70$). Warns of burn rate approaching limits.
  3. **GREEN (`cost-green`)**: Day spend is $< 70\%$ of baseline ($<\$0.49$). Reflects nominal operating parameters.

---

## 3. Succinct Acronym Formation & Tooltips

In the "Daily Cost History (Last 30 Days)" table, the former `Net` and `Credits applied` columns are removed. In their place, a single **Top 5 Services** column displays the top 5 spend drivers succinctly:

$$\text{Format: } \text{ACRONYM}(\$\text{Amount}; \text{Percent}\%)$$

### Acronym Rule Algorithm
1. Strip leading `"Amazon "` or `"AWS "` or `"Amazon/AWS "`.
2. Map standard prominent AWS service names to well-recognized industry acronyms:
   - *Amazon Relational Database Service* $\rightarrow$ `RDS`
   - *AWS CloudWatch / AmazonCloudWatch* $\rightarrow$ `CW`
   - *Amazon Simple Storage Service* $\rightarrow$ `S3`
   - *AWS Lambda* $\rightarrow$ `LAM`
   - *Amazon DynamoDB* $\rightarrow$ `DDB`
   - *AWS Key Management Service* $\rightarrow$ `KMS`
   - *Amazon Route 53* $\rightarrow$ `R53`
   - *AWS Cost Explorer* $\rightarrow$ `CE`
   - *Amazon Virtual Private Cloud* $\rightarrow$ `VPC`
3. For any other service, extract the first 3 alphanumeric characters of the stripped name (uppercase).
4. **Interactive Hyperlink Tooltip**: Each badge is wrapped in an anchor element with a detailed HTML `title` attribute:
   ```html
   <a href="javascript:void(0)" class="svc-badge" title="Amazon Relational Database Service: $0.90 (75%)">RDS($0.90; 75%)</a>
   ```

---

## 4. Navigable Grid & Sorting

- **Pagination**: Daily cost records are paginated at **10 records per page**.
- **Navigation Controls**: `Previous` and `Next` buttons, page summary indicator (`Showing 1–10 of 30 days (Page 1 of 3)`), with automated disable states on boundary pages.
- **Sorting**: Clickable table column headers (`Date (UTC)`, `Gross (USD)`). Allows bi-directional ascending/descending sort with directional indicator arrows (`▲` / `▼`).

---

## 5. Sub-Costs & Trend Sparklines

- **Top Services Spend**:
  - Displays 30-day gross spend and percentage share.
  - **Trend (30d)**: Real-time SVG sparkline visualizes daily trajectory across the window.
  - **Top 3 Sub-Costs**: Every top service breaks down into its top 3 cost components (e.g. `Aurora Serverless v2 ACU`, `Storage and IOs`, `Backup Retention`).
- **Breakdown by ApplicationName Tag**:
  - 30-day roll-up grouped by `ApplicationName` tag.
  - Progress bar indicates share distribution across applications.
