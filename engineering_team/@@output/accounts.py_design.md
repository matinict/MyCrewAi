## 
# accounts.py

class Account:
    """
    A class to manage a user's account in a trading simulation platform.
    """

    def __init__(self, username: str, initial_deposit: float = 0.0):
        """
        Initializes an account with a username and an initial deposit.
        
        :param username: The name of the user.
        :param initial_deposit: The initial deposit to fund the account.
        """
        self.username = username
        self.balance = initial_deposit
        self.holdings = {}
        self.transactions = []

    def deposit(self, amount: float):
        """
        Deposits funds into the account.
        
        :param amount: The amount to deposit.
        """
        if amount <= 0:
            raise ValueError("Deposit amount must be positive.")
        self.balance += amount
        self.transactions.append(f"Deposited: ${amount:.2f}")

    def withdraw(self, amount: float):
        """
        Withdraws funds from the account.
        
        :param amount: The amount to withdraw.
        """
        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive.")
        if self.balance - amount < 0:
            raise ValueError("Insufficient balance for withdrawal.")
        self.balance -= amount
        self.transactions.append(f"Withdrew: ${amount:.2f}")

    def buy_shares(self, symbol: str, quantity: int):
        """
        Buys shares of a specific stock.
        
        :param symbol: The stock symbol.
        :param quantity: The number of shares to buy.
        """
        if quantity <= 0:
            raise ValueError("Quantity must be positive.")
        price_per_share = get_share_price(symbol)
        total_cost = price_per_share * quantity
        if total_cost > self.balance:
            raise ValueError("Insufficient funds to buy shares.")
        
        # Deduct funds and record the transaction
        self.balance -= total_cost
        if symbol in self.holdings:
            self.holdings[symbol] += quantity
        else:
            self.holdings[symbol] = quantity
        self.transactions.append(f"Bought: {quantity} shares of {symbol} at ${price_per_share:.2f}")

    def sell_shares(self, symbol: str, quantity: int):
        """
        Sells shares of a specific stock.
        
        :param symbol: The stock symbol.
        :param quantity: The number of shares to sell.
        """
        if quantity <= 0:
            raise ValueError("Quantity must be positive.")
        if symbol not in self.holdings or self.holdings[symbol] < quantity:
            raise ValueError("Insufficient shares to sell.")
        
        price_per_share = get_share_price(symbol)
        total_revenue = price_per_share * quantity
        
        # Adjust holdings and record transaction
        self.holdings[symbol] -= quantity
        if self.holdings[symbol] == 0:
            del self.holdings[symbol]
        self.balance += total_revenue
        self.transactions.append(f"Sold: {quantity} shares of {symbol} at ${price_per_share:.2f}")

    def get_portfolio_value(self) -> float:
        """
        Calculates the total value of the user's portfolio.
        
        :return: The total value of the portfolio.
        """
        total_value = self.balance
        for symbol, quantity in self.holdings.items():
            total_value += get_share_price(symbol) * quantity
        return total_value

    def get_profit_loss(self) -> float:
        """
        Calculates the profit or loss since the initial deposit.
        
        :return: The profit or loss amount.
        """
        return self.get_portfolio_value() - self.initial_deposit

    def get_holdings(self) -> dict:
        """
        Returns the current holdings of the user.
        
        :return: A dictionary of holdings (stock symbol and quantity).
        """
        return self.holdings.copy()

    def get_profit_loss_summary(self) -> float:
        """
        Returns the current profit or loss.
        
        :return: The profit or loss amount.
        """
        return self.get_profit_loss()

    def get_transactions(self) -> list:
        """
        Returns the list of transactions.
        
        :return: A list of transaction strings.
        """
        return self.transactions.copy()

def get_share_price(symbol: str) -> float:
    """
    Test implementation to get the share price for predefined symbols.
    
    :param symbol: The stock symbol.
    :return: The current price of the share.
    """
    prices = {
        "AAPL": 150.0,
        "TSLA": 700.0,
        "GOOGL": 2800.0
    }
    return prices.get(symbol, 0.0)
 