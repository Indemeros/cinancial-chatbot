"""
Generate sample transaction data for testing the Financial AI Assistant
Run this script to create a sample_data.csv file
"""

import pandas as pd
import random
from datetime import datetime, timedelta

# Sample data configuration
categories = ['Food', 'Transport', 'Entertainment', 'Shopping', 'Health', 'Bills', 'Salary', 'Freelance']
merchants = {
    'Food': ['WHOLE FOODS', 'STARBUCKS', 'MCDONALDS', 'LOCAL RESTAURANT', 'GROCERY STORE'],
    'Transport': ['UBER', 'LYFT', 'GAS STATION', 'PUBLIC TRANSIT', 'PARKING'],
    'Entertainment': ['NETFLIX', 'SPOTIFY', 'CINEMA', 'CONCERT VENUE', 'STEAM'],
    'Shopping': ['AMAZON', 'TARGET', 'WALMART', 'BEST BUY', 'ONLINE STORE'],
    'Health': ['PHARMACY', 'GYM MEMBERSHIP', 'DOCTOR OFFICE', 'DENTAL CLINIC'],
    'Bills': ['ELECTRIC COMPANY', 'WATER UTILITY', 'INTERNET PROVIDER', 'PHONE COMPANY'],
    'Salary': ['EMPLOYER INC', 'COMPANY LLC'],
    'Freelance': ['CLIENT A', 'CLIENT B', 'UPWORK', 'FIVERR']
}

currencies = ['USD', 'EUR', 'GBP']
accounts = ['checking_001', 'savings_001', 'credit_card_001']

def generate_transactions(num_transactions=200, start_date='2023-09-01', end_date='2024-02-28'):
    """Generate sample transaction data"""
    
    transactions = []
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    
    for _ in range(num_transactions):
        # Random date
        days_between = (end - start).days
        random_days = random.randint(0, days_between)
        transaction_date = start + timedelta(days=random_days)
        
        # Random category
        category = random.choice(categories)
        
        # Determine transaction type
        if category in ['Salary', 'Freelance']:
            transaction_type = 'income'
            amount_range = (1000, 5000)
        else:
            transaction_type = 'outcome'
            if category == 'Bills':
                amount_range = (50, 300)
            elif category == 'Shopping':
                amount_range = (20, 500)
            elif category == 'Food':
                amount_range = (5, 150)
            elif category == 'Transport':
                amount_range = (3, 80)
            elif category == 'Entertainment':
                amount_range = (10, 200)
            else:
                amount_range = (10, 300)
        
        # Random merchant
        merchant = random.choice(merchants[category])
        
        # Random currency
        currency = random.choice(currencies)
        
        # Random amount
        amount = round(random.uniform(*amount_range), 2)
        
        # Convert to user's default currency (assuming USD as default)
        conversion_rates = {'USD': 1.0, 'EUR': 1.1, 'GBP': 1.25}
        amount_uc = round(amount * conversion_rates[currency], 2)
        
        # Random account
        account = random.choice(accounts)
        
        transaction = {
            'date': transaction_date.strftime('%Y-%m-%d'),
            'account': account,
            'category': category,
            'merchant': merchant,
            'transaction_type': transaction_type,
            'currency': currency,
            'amount': amount,
            'amount_uc': amount_uc
        }
        
        transactions.append(transaction)
    
    # Create DataFrame
    df = pd.DataFrame(transactions)
    
    # Sort by date
    df = df.sort_values('date').reset_index(drop=True)
    
    return df

if __name__ == "__main__":
    print("Generating sample transaction data...")
    df = generate_transactions(num_transactions=200)
    
    # Save to CSV
    df.to_csv('sample_data.csv', index=False)
    
    print(f"✅ Generated {len(df)} transactions")
    print(f"📅 Date range: {df['date'].min()} to {df['date'].max()}")
    print(f"💰 Total spending: ${df[df['transaction_type']=='outcome']['amount_uc'].sum():.2f}")
    print(f"💵 Total income: ${df[df['transaction_type']=='income']['amount_uc'].sum():.2f}")
    print("\nSample data saved to: sample_data.csv")
    print("\nFirst few transactions:")
    print(df.head(10).to_string())
