import gradio as gr
from accounts import Account, get_share_price
from datetime import datetime

# Global account instance (single user demo)
account = None

def create_account(initial_deposit):
    global account
    try:
        initial_deposit = float(initial_deposit)
        if initial_deposit <= 0:
            return "Error: Initial deposit must be positive", get_account_info()
        account = Account(initial_deposit)
        return f"Account created successfully with initial deposit: ${initial_deposit:.2f}", get_account_info()
    except ValueError:
        return "Error: Invalid deposit amount", get_account_info()
    except Exception as e:
        return f"Error: {str(e)}", get_account_info()

def deposit_funds(amount):
    global account
    if account is None:
        return "Error: Please create an account first", get_account_info()
    try:
        amount = float(amount)
        account.deposit(amount)
        return f"Successfully deposited ${amount:.2f}", get_account_info()
    except ValueError as e:
        return f"Error: {str(e)}", get_account_info()
    except Exception as e:
        return f"Error: {str(e)}", get_account_info()

def withdraw_funds(amount):
    global account
    if account is None:
        return "Error: Please create an account first", get_account_info()
    try:
        amount = float(amount)
        account.withdraw(amount)
        return f"Successfully withdrew ${amount:.2f}", get_account_info()
    except ValueError as e:
        return f"Error: {str(e)}", get_account_info()
    except Exception as e:
        return f"Error: {str(e)}", get_account_info()

def buy_shares(symbol, quantity):
    global account
    if account is None:
        return "Error: Please create an account first", get_account_info(), get_holdings()
    try:
        quantity = int(quantity)
        account.buy(symbol.upper(), quantity)
        return f"Successfully bought {quantity} shares of {symbol.upper()}", get_account_info(), get_holdings()
    except ValueError as e:
        return f"Error: {str(e)}", get_account_info(), get_holdings()
    except Exception as e:
        return f"Error: {str(e)}", get_account_info(), get_holdings()

def sell_shares(symbol, quantity):
    global account
    if account is None:
        return "Error: Please create an account first", get_account_info(), get_holdings()
    try:
        quantity = int(quantity)
        account.sell(symbol.upper(), quantity)
        return f"Successfully sold {quantity} shares of {symbol.upper()}", get_account_info(), get_holdings()
    except ValueError as e:
        return f"Error: {str(e)}", get_account_info(), get_holdings()
    except Exception as e:
        return f"Error: {str(e)}", get_account_info(), get_holdings()

def get_account_info():
    if account is None:
        return "No account created yet"
    
    try:
        info = []
        info.append(f"💰 Cash Balance: ${account.cash:.2f}")
        info.append(f"📊 Portfolio Value: ${account.portfolio_value():.2f}")
        info.append(f"💵 Initial Deposit: ${account.initial_deposit:.2f}")
        
        profit_loss = account.profit_loss()
        if profit_loss >= 0:
            info.append(f"📈 Profit/Loss: ${profit_loss:.2f} ({(profit_loss/account.initial_deposit*100):.2f}%)")
        else:
            info.append(f"📉 Profit/Loss: -${abs(profit_loss):.2f} ({(profit_loss/account.initial_deposit*100):.2f}%)")
        
        return "\n".join(info)
    except Exception as e:
        return f"Error getting account info: {str(e)}"

def get_holdings():
    if account is None:
        return "No account created yet"
    
    try:
        holdings = account.report_holdings()
        if not holdings:
            return "No holdings"
        
        holdings_str = []
        holdings_str.append("Current Holdings:")
        holdings_str.append("-" * 40)
        
        total_value = 0
        for symbol, quantity in holdings.items():
            price = get_share_price(symbol)
            value = price * quantity
            total_value += value
            holdings_str.append(f"{symbol}: {quantity} shares @ ${price:.2f} = ${value:.2f}")
        
        holdings_str.append("-" * 40)
        holdings_str.append(f"Total Holdings Value: ${total_value:.2f}")
        
        return "\n".join(holdings_str)
    except Exception as e:
        return f"Error getting holdings: {str(e)}"

def get_transactions():
    if account is None:
        return "No account created yet"
    
    try:
        transactions = account.report_transactions()
        if not transactions:
            return "No transactions yet"
        
        trans_str = []
        trans_str.append("Transaction History:")
        trans_str.append("-" * 60)
        
        for trans in transactions:
            timestamp = trans['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
            trans_type = trans['type']
            
            if trans_type in ['deposit', 'withdrawal']:
                amount = trans['amount']
                trans_str.append(f"[{timestamp}] {trans_type.upper()}: ${amount:.2f}")
            else:  # buy or sell
                symbol = trans['symbol']
                quantity = trans['quantity']
                price = trans['price']
                total = price * quantity
                trans_str.append(f"[{timestamp}] {trans_type.upper()} {symbol}: {quantity} shares @ ${price:.2f} = ${total:.2f}")
        
        return "\n".join(trans_str)
    except Exception as e:
        return f"Error getting transactions: {str(e)}"

def get_stock_prices():
    symbols = ['AAPL', 'TSLA', 'GOOGL']
    prices = []
    for symbol in symbols:
        price = get_share_price(symbol)
        prices.append(f"{symbol}: ${price:.2f}")
    return "Available Stocks:\n" + "\n".join(prices)

# Create the Gradio interface
with gr.Blocks(title="Trading Account Demo") as app:
    gr.Markdown("# 📈 Trading Account Management System")
    gr.Markdown("A simple trading simulation platform where you can manage funds and trade stocks.")
    
    with gr.Row():
        with gr.Column(scale=1):
            gr.Markdown("### Account Setup")
            initial_deposit_input = gr.Number(label="Initial Deposit ($)", value=1000)
            create_account_btn = gr.Button("Create Account", variant="primary")
            account_message = gr.Textbox(label="Status", lines=1)
            
            gr.Markdown("### Fund Management")
            deposit_amount = gr.Number(label="Deposit Amount ($)")
            deposit_btn = gr.Button("Deposit Funds")
            
            withdraw_amount = gr.Number(label="Withdraw Amount ($)")
            withdraw_btn = gr.Button("Withdraw Funds")
            
            gr.Markdown("### Stock Trading")
            stock_prices_display = gr.Textbox(label="Stock Prices", value=get_stock_prices(), lines=4)
            
            with gr.Row():
                trade_symbol = gr.Dropdown(choices=["AAPL", "TSLA", "GOOGL"], label="Stock Symbol", value="AAPL")
                trade_quantity = gr.Number(label="Quantity", value=1, precision=0)
            
            with gr.Row():
                buy_btn = gr.Button("Buy Shares", variant="primary")
                sell_btn = gr.Button("Sell Shares", variant="stop")
            
            trade_message = gr.Textbox(label="Trade Status", lines=1)
        
        with gr.Column(scale=1):
            gr.Markdown("### Account Information")
            account_info_display = gr.Textbox(label="Account Summary", lines=5, value=get_account_info())
            
            gr.Markdown("### Portfolio Holdings")
            holdings_display = gr.Textbox(label="Current Holdings", lines=8, value=get_holdings())
            
            gr.Markdown("### Transaction History")
            transactions_display = gr.Textbox(label="All Transactions", lines=10, value=get_transactions())
            
            refresh_btn = gr.Button("🔄 Refresh All", variant="secondary")
    
    # Event handlers
    create_account_btn.click(
        create_account,
        inputs=[initial_deposit_input],
        outputs=[account_message, account_info_display]
    )
    
    deposit_btn.click(
        deposit_funds,
        inputs=[deposit_amount],
        outputs=[account_message, account_info_display]
    ).then(
        get_transactions,
        outputs=[transactions_display]
    )
    
    withdraw_btn.click(
        withdraw_funds,
        inputs=[withdraw_amount],
        outputs=[account_message, account_info_display]
    ).then(
        get_transactions,
        outputs=[transactions_display]
    )
    
    buy_btn.click(
        buy_shares,
        inputs=[trade_symbol, trade_quantity],
        outputs=[trade_message, account_info_display, holdings_display]
    ).then(
        get_transactions,
        outputs=[transactions_display]
    )
    
    sell_btn.click(
        sell_shares,
        inputs=[trade_symbol, trade_quantity],
        outputs=[trade_message, account_info_display, holdings_display]
    ).then(
        get_transactions,
        outputs=[transactions_display]
    )
    
    refresh_btn.click(
        lambda: (get_account_info(), get_holdings(), get_transactions(), get_stock_prices()),
        outputs=[account_info_display, holdings_display, transactions_display, stock_prices_display]
    )

if __name__ == "__main__":
    app.launch()