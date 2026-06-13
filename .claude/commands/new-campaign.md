Run a new marketing campaign for the cafe.

**Usage:** `/new-campaign <brief>`

**Example:** `/new-campaign latte art competition, goal: +200 followers, format: Reel+Stories, duration: 7 days`

Steps:
1. Parse the brief from $ARGUMENTS (product/event, goal, format, duration)
2. Run Strategy node to build a 7-day content calendar
3. Run Creative node to draft captions + asset list for each post
4. Output the full draft for human approval — do NOT call any publishing tool until approved

Campaign start date: !`date +"%Y-%m-%d"`
