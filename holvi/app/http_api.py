"""
This is the place to implement Holvi's integration!
"""

import os

from flask import Flask

from database import DBConnection
from payout_service import PayoutService

app = Flask(__name__)

EXPENZY_API_BASE_URL = os.environ.get("EXPENZY_API_BASE_URL", "127.0.0.1")


@app.route("/expenzy/webhook/", methods=["GET"])
def expenzy_webhook():
    print("Webhook received")
    # Here we are getting the notification from expenzy
    service = None
    try:
        # Create service and process webhook
        service = PayoutService()
        service.process_webhook()
        return "ok"
    except Exception as e:
        print(f"Error processing webhook: {e}")
        # Return ok (webhook received, even on error)
        return "ok"
    finally:
        if service:
            service.close()


@app.route("/payout/count", methods=["GET"])
def payout_count():
    """
    A small helper for db_check.py to fetch amount of recorded payouts.
    """
    (num_payouts,) = create_database_connection().fetch_one("SELECT COUNT(*) FROM holvi_received_payout")

    return str(num_payouts)


def create_database_connection():
    return DBConnection(
        hostname=os.environ.get("DB_HOSTNAME", "127.0.0.1"),
        username=os.environ.get("DB_USERNAME", "shared"),
        password=os.environ.get("DB_PASSWORD", "shared"),
        database=os.environ.get("DB_DATABASE", "shared"),
    )


if __name__ == "__main__":
    app.run(debug=True, host="holvi-api", port=5002)
