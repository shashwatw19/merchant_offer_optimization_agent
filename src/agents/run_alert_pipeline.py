import asyncio
import sys
from pathlib import Path
 
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
 
from agents.agent import process_alert_async
from agents.tools.alert_store import (
    ensure_alert_table,
    fetch_pending_alerts,
    # update_alert_status,
)
 
 
async def process_alert_batch(alerts):
    for alert in alerts:
        try:
            response = await process_alert_async(alert)
            print(f"Processed alert {alert['alert_id']}")
            print(response[:500])
            # update_alert_status(alert["alert_id"], "PROCESSED")
        except Exception as exc:
            # update_alert_status(alert["alert_id"], "ERROR")
             print(f"Failed for alert {alert['alert_id']}: {exc}")
 
 
def main() -> None:
    ensure_alert_table()
    pending_alerts = fetch_pending_alerts(limit=2)
 
    if not pending_alerts:
        print("No OPEN alerts found in alerts.csv")
        return
 
    asyncio.run(process_alert_batch(pending_alerts))
 
 
if __name__ == "__main__":
    main()
 