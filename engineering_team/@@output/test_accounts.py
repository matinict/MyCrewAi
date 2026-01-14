import unittest
import json
from unittest.mock import patch, MagicMock
from accounts import Account, AccountManager

class TestAccount(unittest.TestCase):
    def setUp(self):
        self.account_data = {
            "account_id": "12345",
            "balance": 1000.0,
            "currency": "USD",
            "status": "active",
            "owner": "John Doe"
        }
        self.account = Account(**self.account_data)

    def test_account_initialization(self):
        self.assertEqual(self.account.account_id, "12345")
        self.assertEqual(self.account.balance, 1000.0)
        self.assertEqual(self.account.currency, "USD")
        self.assertEqual(self.account.status, "active")
        self.assertEqual(self.account.owner, "John Doe")

    def test_deposit(self):
        self.account.deposit(500.0)
        self.assertEqual(self.account.balance, 1500.0)

    def test_deposit_negative_amount(self):
        with self.assertRaises(ValueError):
            self.account.deposit(-100.0)

    def test_withdraw_sufficient_balance(self):
        result = self.account.withdraw(300.0)
        self.assertTrue(result)
        self.assertEqual(self.account.balance, 700.0)

    def test_withdraw_insufficient_balance(self):
        result = self.account.withdraw(1500.0)
        self.assertFalse(result)
        self.assertEqual(self.account.balance, 1000.0)

    def test_withdraw_negative_amount(self):
        with self.assertRaises(ValueError):
            self.account.withdraw(-200.0)

    def test_get_info(self):
        info = self.account.get_info()
        expected_info = {
            "account_id": "12345",
            "balance": 1000.0,
            "currency": "USD",
            "status": "active",
            "owner": "John Doe"
        }
        self.assertEqual(info, expected_info)

    def test_set_status(self):
        self.account.set_status("suspended")
        self.assertEqual(self.account.status, "suspended")

    def test_set_status_invalid(self):
        with self.assertRaises(ValueError):
            self.account.set_status("invalid_status")

class TestAccountManager(unittest.TestCase):
    def setUp(self):
        self.manager = AccountManager()
        self.test_account = Account(
            account_id="12345",
            balance=1000.0,
            currency="USD",
            status="active",
            owner="John Doe"
        )

    @patch('accounts.AccountManager.save_to_file')
    def test_add_account(self, mock_save):
        self.manager.add_account(self.test_account)
        self.assertIn("12345", self.manager.accounts)
        self.assertEqual(self.manager.accounts["12345"], self.test_account)
        mock_save.assert_called_once()

    def test_get_account_exists(self):
        self.manager.accounts["12345"] = self.test_account
        account = self.manager.get_account("12345")
        self.assertEqual(account, self.test_account)

    def test_get_account_not_exists(self):
        account = self.manager.get_account("99999")
        self.assertIsNone(account)

    @patch('accounts.AccountManager.save_to_file')
    def test_remove_account_exists(self, mock_save):
        self.manager.accounts["12345"] = self.test_account
        result = self.manager.remove_account("12345")
        self.assertTrue(result)
        self.assertNotIn("12345", self.manager.accounts)
        mock_save.assert_called_once()

    @patch('accounts.AccountManager.save_to_file')
    def test_remove_account_not_exists(self, mock_save):
        result = self.manager.remove_account("99999")
        self.assertFalse(result)
        mock_save.assert_not_called()

    def test_list_accounts(self):
        account2 = Account(
            account_id="67890",
            balance=2000.0,
            currency="EUR",
            status="active",
            owner="Jane Smith"
        )
        self.manager.accounts = {
            "12345": self.test_account,
            "67890": account2
        }
        accounts_list = self.manager.list_accounts()
        self.assertEqual(len(accounts_list), 2)
        self.assertIn(self.test_account, accounts_list)
        self.assertIn(account2, accounts_list)

    @patch('builtins.open', new_callable=unittest.mock.mock_open)
    @patch('json.dump')
    def test_save_to_file(self, mock_json_dump, mock_file):
        self.manager.accounts["12345"] = self.test_account
        self.manager.save_to_file()
        mock_file.assert_called_once_with('accounts_data.json', 'w')
        expected_data = {
            "12345": {
                "account_id": "12345",
                "balance": 1000.0,
                "currency": "USD",
                "status": "active",
                "owner": "John Doe"
            }
        }
        mock_json_dump.assert_called_once_with(expected_data, mock_file(), indent=4)

    @patch('builtins.open', new_callable=unittest.mock.mock_open, read_data=json.dumps({
        "12345": {
            "account_id": "12345",
            "balance": 1000.0,
            "currency": "USD",
            "status": "active",
            "owner": "John Doe"
        }
    }))
    def test_load_from_file_exists(self, mock_file):
        self.manager.load_from_file()
        self.assertIn("12345", self.manager.accounts)
        account = self.manager.accounts["12345"]
        self.assertEqual(account.account_id, "12345")
        self.assertEqual(account.balance, 1000.0)
        self.assertEqual(account.currency, "USD")
        self.assertEqual(account.status, "active")
        self.assertEqual(account.owner, "John Doe")

    @patch('builtins.open', side_effect=FileNotFoundError)
    def test_load_from_file_not_exists(self, mock_file):
        self.manager.load_from_file()
        self.assertEqual(self.manager.accounts, {})

    def test_transfer_success(self):
        account1 = Account(account_id="A1", balance=1000.0, currency="USD", status="active", owner="Alice")
        account2 = Account(account_id="A2", balance=500.0, currency="USD", status="active", owner="Bob")
        self.manager.accounts = {"A1": account1, "A2": account2}
        
        result = self.manager.transfer("A1", "A2", 300.0)
        self.assertTrue(result)
        self.assertEqual(account1.balance, 700.0)
        self.assertEqual(account2.balance, 800.0)

    def test_transfer_sender_not_exists(self):
        account2 = Account(account_id="A2", balance=500.0, currency="USD", status="active", owner="Bob")
        self.manager.accounts = {"A2": account2}
        
        result = self.manager.transfer("A1", "A2", 300.0)
        self.assertFalse(result)

    def test_transfer_receiver_not_exists(self):
        account1 = Account(account_id="A1", balance=1000.0, currency="USD", status="active", owner="Alice")
        self.manager.accounts = {"A1": account1}
        
        result = self.manager.transfer("A1", "A2", 300.0)
        self.assertFalse(result)

    def test_transfer_insufficient_balance(self):
        account1 = Account(account_id="A1", balance=200.0, currency="USD", status="active", owner="Alice")
        account2 = Account(account_id="A2", balance=500.0, currency="USD", status="active", owner="Bob")
        self.manager.accounts = {"A1": account1, "A2": account2}
        
        result = self.manager.transfer("A1", "A2", 300.0)
        self.assertFalse(result)
        self.assertEqual(account1.balance, 200.0)
        self.assertEqual(account2.balance, 500.0)

    def test_transfer_different_currency(self):
        account1 = Account(account_id="A1", balance=1000.0, currency="USD", status="active", owner="Alice")
        account2 = Account(account_id="A2", balance=500.0, currency="EUR", status="active", owner="Bob")
        self.manager.accounts = {"A1": account1, "A2": account2}
        
        result = self.manager.transfer("A1", "A2", 300.0)
        self.assertFalse(result)

    def test_transfer_inactive_sender(self):
        account1 = Account(account_id="A1", balance=1000.0, currency="USD", status="suspended", owner="Alice")
        account2 = Account(account_id="A2", balance=500.0, currency="USD", status="active", owner="Bob")
        self.manager.accounts = {"A1": account1, "A2": account2}
        
        result = self.manager.transfer("A1", "A2", 300.0)
        self.assertFalse(result)

    def test_transfer_inactive_receiver(self):
        account1 = Account(account_id="A1", balance=1000.0, currency="USD", status="active", owner="Alice")
        account2 = Account(account_id="A2", balance=500.0, currency="USD", status="suspended", owner="Bob")
        self.manager.accounts = {"A1": account1, "A2": account2}
        
        result = self.manager.transfer("A1", "A2", 300.0)
        self.assertFalse(result)

    def test_total_balance(self):
        account1 = Account(account_id="A1", balance=1000.0, currency="USD", status="active", owner="Alice")
        account2 = Account(account_id="A2", balance=500.0, currency="USD", status="active", owner="Bob")
        account3 = Account(account_id="A3", balance=250.0, currency="EUR", status="active", owner="Charlie")
        self.manager.accounts = {"A1": account1, "A2": account2, "A3": account3}
        
        total = self.manager.total_balance("USD")
        self.assertEqual(total, 1500.0)

    def test_total_balance_no_accounts(self):
        total = self.manager.total_balance("USD")
        self.assertEqual(total, 0.0)

    def test_total_balance_currency_no_match(self):
        account1 = Account(account_id="A1", balance=1000.0, currency="USD", status="active", owner="Alice")
        self.manager.accounts = {"A1": account1}
        
        total = self.manager.total_balance("EUR")
        self.assertEqual(total, 0.0)

    def test_apply_interest(self):
        account = Account(account_id="A1", balance=1000.0, currency="USD", status="active", owner="Alice")
        self.manager.accounts = {"A1": account}
        
        self.manager.apply_interest("A1", 5.0)  # 5% interest
        self.assertEqual(account.balance, 1050.0)

    def test_apply_interest_account_not_exists(self):
        result = self.manager.apply_interest("A1", 5.0)
        self.assertFalse(result)

    def test_apply_interest_inactive_account(self):
        account = Account(account_id="A1", balance=1000.0, currency="USD", status="suspended", owner="Alice")
        self.manager.accounts = {"A1": account}
        
        result = self.manager.apply_interest("A1", 5.0)
        self.assertFalse(result)
        self.assertEqual(account.balance, 1000.0)

    def test_apply_interest_negative_rate(self):
        account = Account(account_id="A1", balance=1000.0, currency="USD", status="active", owner="Alice")
        self.manager.accounts = {"A1": account}
        
        with self.assertRaises(ValueError):
            self.manager.apply_interest("A1", -5.0)

if __name__ == '__main__':
    unittest.main()