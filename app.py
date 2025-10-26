import streamlit as st
import pandas as pd
import json
import os
from dataclasses import dataclass
from typing import List
from openai import OpenAI
import io

# Page configuration
st.set_page_config(
    page_title="Financial AI Assistant",
    page_icon="💰",
    layout="wide"
)

# Initialize session state
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'transaction_list' not in st.session_state:
    st.session_state.transaction_list = None
if 'local_info' not in st.session_state:
    st.session_state.local_info = None

# Transaction class
@dataclass
class Transaction:
    date: str
    account: str
    category: str
    merchant: str
    transaction_type: str
    currency: str
    amount: float
    amount_uc: float

# Prompts
PROMPT_CONTEXT_PYTHON = """
*Introduction*
We handle personal financial transactions, helping users analyze and gain insights from their data.

Here are the descriptors of each transaction:
- date (string, YYYY-MM-DD): Transaction date.
- account_id (string): Account identifier.
- category (string): User-defined transaction type (e.g., 'Food', 'Leisure'). Users typically have 10-40 categories.
- merchant (string): Merchant name (e.g., 'AMAZON', 'APPLE').
- transaction_type (string): 'income' or 'outcome'.
- currency (string): Transaction currency code (e.g., 'USD', 'EUR', 'GBP').
- amount (float): Transaction amount in the original currency (non-negative). If asked about original transactions, make sure to user original amount, i.e. amount.
- amount_uc (float): Transaction amount in the user's default currency (non-negative). If asked about general information/statistics on user's transactions, make sure to use amount in user's default currency, i.e. amount_uc.

*Task*
You will be given a query in natural language that pertains to a user's financial transactions.
Your job is to generate a response in JSON format that contains the following keys:

1. "is_relevant": (Boolean) True if the query is about the user's financial transactions, False otherwise.
2. "needs_diagram": (Boolean) True if the query requires a visual representation.
3. "context_code": (String) A Python function named `get_context` that processes the `transaction_list` and returns a dictionary containing the necessary context to answer the query.
4. "algorithm_explanation": (String) A high level explanation of the algorithm from 'context_code' using user's default language '{user_language}'.
5. "diagram_code": (String) A Python function named `plot` that uses matplotlib/seaborn to create a visualization (only if needs_diagram is True).

*Input Context*:
  * Current date: {latest_date}
  * Date range for transactions: From {start_date} to {latest_date}
  * User's default currency: '{currency}'
  * User's default language: '{user_language}'
  * User's Unique Categories: {unique_categories}
  * User's unique currencies: {unique_currencies}

Query: {question}

*Format*:
- Ensure the code is clean, well-formatted, and efficient.
- Use function names get_context and plot exactly as specified.
- Only use datetime and matplotlib/seaborn libraries if needed.
- If query is irrelevant or asks for dates outside range, return: {{"is_relevant": false,"needs_diagram": false,"context_code": "","algorithm_explanation":"","diagram_code": ""}}

Output as JSON string.
"""

PROMPT_OUTPUT = """
**Task**: You are an expert data analyst. You are given the following context to answer the given question.

**Context**:
{context}

**Question**
{question}

**Additional Information**:
  * Country code of the user: '{user_country}'
  * Default language code of the user: '{user_language}'. Provide your response in user's default language.
  * Default currency code of the user: '{currency}'. If no currency information given assume the default currency.
  * Format monetary values with two decimal places. Remove trailing zeros.
  * Use appropriate formatting for the currency, e.g. $10.65, £12.34, 50.25₾ etc.
  * If context is empty, respond with "We don't have such information" in appropriate language.
  * Only provide the answer. Do not include the question.

**Format and Tone**:
  * Provide clear and concise answers.
  * Use a friendly and professional tone.
  * Provide the final output only.
"""

def df_to_transaction_list(df: pd.DataFrame) -> List[Transaction]:
    """Convert DataFrame to list of Transaction objects"""
    transactions = []
    for _, row in df.iterrows():
        transaction = Transaction(
            date=str(row['date']),
            account=str(row['account']),
            category=str(row['category']),
            merchant=str(row['merchant']),
            transaction_type=str(row['transaction_type']),
            currency=str(row['currency']),
            amount=float(row['amount']),
            amount_uc=float(row['amount_uc'])
        )
        transactions.append(transaction)
    return transactions

def run_prompt(client, prompt, system_message, output_format):
    """Call OpenAI API"""
    try:
        if output_format == 'text':
            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                max_tokens=2048,
            )
        else:  # json
            completion = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                max_tokens=2048,
                response_format={"type": "json_object"}
            )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        st.error(f"API Error: {str(e)}")
        return None

def process_question(client, question, transaction_list, local_info):
    """Process user question and generate response"""
    
    # Extract metadata
    unique_categories = str(set(t.category for t in transaction_list))
    unique_currencies = str(set(t.currency for t in transaction_list))
    
    # Generate code
    system_message = "You are a helpful assistant that generates Python code for financial data analysis."
    full_prompt = PROMPT_CONTEXT_PYTHON.format(
        question=question,
        unique_categories=unique_categories,
        unique_currencies=unique_currencies,
        **local_info
    )
    
    code_response = run_prompt(client, full_prompt, system_message, 'json')
    if not code_response:
        return None, None, None
    
    try:
        code_dict = json.loads(code_response)
    except json.JSONDecodeError as e:
        st.error(f"Failed to parse code response: {e}")
        return None, None, None
    
    # Check relevance
    if not code_dict.get('is_relevant', False):
        return "Sorry, I can only answer questions about your financial transactions.", None, None
    
    # Execute generated code
    context = {}
    try:
        exec(code_dict['context_code'], globals())
        context = get_context(transaction_list)
    except Exception as e:
        st.error(f"Error executing generated code: {str(e)}")
        return None, None, None
    
    # Generate natural language output
    system_message = "You are a helpful financial assistant."
    output_prompt = PROMPT_OUTPUT.format(
        question=question,
        context=context,
        **local_info
    )
    
    output = run_prompt(client, output_prompt, system_message, 'text')
    
    # Handle diagram if needed
    diagram = None
    if code_dict.get('needs_diagram', False) and code_dict.get('diagram_code'):
        try:
            exec(code_dict['diagram_code'], globals())
            diagram = plot(context)
        except Exception as e:
            st.warning(f"Could not generate diagram: {str(e)}")
    
    return output, context, diagram

# Sidebar for configuration
with st.sidebar:
    st.title("⚙️ Configuration")
    
    # API Key input
    api_key = st.text_input("OpenAI API Key", type="password", help="Enter your OpenAI API key")
    
    st.divider()
    
    # File upload
    st.subheader("📁 Upload Transaction Data")
    uploaded_file = st.file_uploader(
        "Upload CSV file",
        type=['csv'],
        help="CSV should contain: date, account, category, merchant, transaction_type, currency, amount, amount_uc"
    )
    
    # User settings
    st.subheader("🌍 User Settings")
    user_language = st.selectbox("Language", ["ENG", "RUS", "GEO"], index=0)
    user_country = st.selectbox("Country", ["USA", "GEO", "RUS"], index=0)
    currency = st.selectbox("Default Currency", ["USD", "GEL", "EUR", "GBP"], index=0)
    
    if uploaded_file and st.button("Load Data"):
        try:
            df = pd.read_csv(uploaded_file)
            st.session_state.transaction_list = df_to_transaction_list(df)
            
            # Extract date range
            dates = [t.date for t in st.session_state.transaction_list]
            start_date = min(dates)
            latest_date = max(dates)
            
            st.session_state.local_info = {
                'user_language': user_language,
                'user_country': user_country,
                'currency': currency,
                'start_date': start_date,
                'latest_date': latest_date
            }
            
            st.success(f"✅ Loaded {len(st.session_state.transaction_list)} transactions")
            st.info(f"Date range: {start_date} to {latest_date}")
        except Exception as e:
            st.error(f"Error loading file: {str(e)}")

# Main content
st.title("💰 Financial AI Assistant")
st.markdown("Ask questions about your financial transactions in natural language!")

# Check if data is loaded
if st.session_state.transaction_list is None:
    st.info("👈 Please upload your transaction data in the sidebar to get started.")
    st.markdown("""
    ### How to use:
    1. Enter your OpenAI API key in the sidebar
    2. Upload a CSV file with your transactions
    3. Configure your preferences (language, currency, etc.)
    4. Start asking questions!
    
    ### Example questions:
    - "How much did I spend in December?"
    - "Show me my largest expenses last month"
    - "What are my top spending categories?"
    - "Did I spend more on food or entertainment?"
    """)
else:
    # Chat interface
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if "context" in message and message["context"]:
                with st.expander("📊 See context data"):
                    st.json(message["context"])
    
    # Chat input
    if prompt := st.chat_input("Ask about your transactions..."):
        if not api_key:
            st.error("Please enter your OpenAI API key in the sidebar!")
        else:
            # Add user message
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
            
            # Generate response
            with st.chat_message("assistant"):
                with st.spinner("Analyzing..."):
                    client = OpenAI(api_key=api_key)
                    response, context, diagram = process_question(
                        client,
                        prompt,
                        st.session_state.transaction_list,
                        st.session_state.local_info
                    )
                    
                    if response:
                        st.markdown(response)
                        
                        # Show context in expander
                        if context:
                            with st.expander("📊 See context data"):
                                st.json(context)
                        
                        # Show diagram if available
                        if diagram:
                            st.pyplot(diagram)
                        
                        # Save to chat history
                        st.session_state.messages.append({
                            "role": "assistant",
                            "content": response,
                            "context": context
                        })
                    else:
                        st.error("Failed to generate response. Please try again.")

# Footer
st.divider()
st.markdown("""
<div style='text-align: center; color: gray;'>
    <small>Built with Streamlit & OpenAI | Your data is processed locally and not stored</small>
</div>
""", unsafe_allow_html=True)
