"""
Firefly III Integration — Personal finance tracking
"""
import os
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)

try:
    import httpx
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False


class FireflyBridge:
    """Firefly III API bridge"""

    def __init__(self):
        self.firefly_url = os.getenv('FIREFLY_URL', 'http://localhost:8080')
        self.firefly_token = os.getenv('FIREFLY_TOKEN')
        self.connected = False

        if self.firefly_token and HTTPX_AVAILABLE:
            self._test_connection()

    def _test_connection(self):
        """Test connection to Firefly III"""
        try:
            with httpx.Client() as client:
                response = client.get(
                    f"{self.firefly_url}/api/v1/about",
                    headers={"Authorization": f"Bearer {self.firefly_token}"},
                    timeout=5.0
                )
                if response.status_code == 200:
                    self.connected = True
                    logger.info("Connected to Firefly III")
        except Exception as e:
            logger.warning(f"Firefly III not reachable: {e}")

    def get_account_summary(self) -> Dict[str, Any]:
        """Get all accounts and their balances"""
        if not self.connected or not HTTPX_AVAILABLE:
            return {"error": "Firefly III not configured", "accounts": []}

        try:
            with httpx.Client() as client:
                response = client.get(
                    f"{self.firefly_url}/api/v1/accounts",
                    headers={"Authorization": f"Bearer {self.firefly_token}"},
                    timeout=10.0
                )
                response.raise_for_status()

                data = response.json()
                accounts = []

                for account in data.get('data', []):
                    attributes = account.get('attributes', {})
                    accounts.append({
                        'name': attributes.get('name'),
                        'type': attributes.get('type'),
                        'balance': float(attributes.get('current_balance', 0)),
                        'currency': attributes.get('currency_code', 'USD')
                    })

                return {"error": None, "accounts": accounts}

        except Exception as e:
            logger.error(f"Failed to get accounts: {e}")
            return {"error": str(e), "accounts": []}

    def get_recent_transactions(self, days: int = 7) -> Dict[str, Any]:
        """Get recent transactions"""
        if not self.connected or not HTTPX_AVAILABLE:
            return {"error": "Firefly III not configured", "transactions": []}

        try:
            from datetime import datetime, timedelta

            start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

            with httpx.Client() as client:
                response = client.get(
                    f"{self.firefly_url}/api/v1/transactions",
                    headers={"Authorization": f"Bearer {self.firefly_token}"},
                    params={"start": start_date},
                    timeout=10.0
                )
                response.raise_for_status()

                data = response.json()
                transactions = []

                for txn in data.get('data', []):
                    attributes = txn.get('attributes', {})
                    transactions_data = attributes.get('transactions', [])

                    if transactions_data:
                        first_txn = transactions_data[0]
                        transactions.append({
                            'description': first_txn.get('description'),
                            'amount': float(first_txn.get('amount', 0)),
                            'date': first_txn.get('date'),
                            'category': first_txn.get('category_name')
                        })

                return {"error": None, "transactions": transactions}

        except Exception as e:
            logger.error(f"Failed to get transactions: {e}")
            return {"error": str(e), "transactions": []}

    def get_budget_status(self) -> Dict[str, Any]:
        """Get budget limits and current spending"""
        if not self.connected or not HTTPX_AVAILABLE:
            return {"error": "Firefly III not configured", "budgets": []}

        try:
            with httpx.Client() as client:
                response = client.get(
                    f"{self.firefly_url}/api/v1/budgets",
                    headers={"Authorization": f"Bearer {self.firefly_token}"},
                    timeout=10.0
                )
                response.raise_for_status()

                data = response.json()
                budgets = []

                for budget in data.get('data', []):
                    attributes = budget.get('attributes', {})
                    budgets.append({
                        'name': attributes.get('name'),
                        'spent': float(attributes.get('spent', [{}])[0].get('sum', 0)),
                        'limit': float(attributes.get('limit', 0))
                    })

                return {"error": None, "budgets": budgets}

        except Exception as e:
            logger.error(f"Failed to get budgets: {e}")
            return {"error": str(e), "budgets": []}

    def get_net_worth(self) -> float:
        """Calculate net worth from all asset accounts"""
        accounts = self.get_account_summary()

        if accounts.get('error'):
            return 0.0

        total = sum(
            acc['balance'] for acc in accounts['accounts']
            if acc['type'] in ['asset', 'default']
        )

        return total

    def finance_summary(self) -> str:
        """Get plain-English finance summary"""
        if not self.connected:
            return "Firefly III not configured"

        net_worth = self.get_net_worth()
        transactions = self.get_recent_transactions(days=7)
        budgets = self.get_budget_status()

        # Calculate week spending
        week_spending = 0.0
        if not transactions.get('error'):
            week_spending = sum(
                abs(t['amount']) for t in transactions['transactions']
                if t['amount'] < 0
            )

        # Budget remaining
        budget_remaining = 0.0
        if not budgets.get('error'):
            for budget in budgets['budgets']:
                budget_remaining += max(0, budget['limit'] - budget['spent'])

        summary = f"Net worth: ${net_worth:,.2f}. "
        summary += f"This week you spent ${week_spending:,.2f}. "

        if budget_remaining > 0:
            summary += f"You have ${budget_remaining:,.2f} left in your budget."

        return summary


# Global instance
_firefly: Optional[FireflyBridge] = None


def get_firefly() -> FireflyBridge:
    """Get or create the global Firefly bridge"""
    global _firefly
    if _firefly is None:
        _firefly = FireflyBridge()
    return _firefly
