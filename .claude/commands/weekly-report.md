Generate the weekly performance report.

Report date: !`date +"%Y-%m-%d"`
Period: past 7 days ending today.

Pull insights via the Analytics node and produce a structured report:

1. **Top 3 posts** by reach (post ID, caption snippet, reach, engagement rate)
2. **Engagement rate** this week vs prior week (delta %)
3. **Follower delta** (net gain/loss)
4. **DM volume** — total received, replied, escalated to human
5. **Manual publish queue** — any items pending (e.g. trending-audio Reels)
6. **Recommended focus** for next week based on what performed

Output as markdown. Flag any metric that is outside the normal range with ⚠.
