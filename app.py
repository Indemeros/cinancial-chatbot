import streamlit as st
import pandas as pd
import json
import os
from dataclasses import dataclass
from typing import List
from openai import OpenAI
import plotly.graph_objects as go
import plotly.express as px

# Get API Key from Streamlit Secrets (secure method)
try:
    OPENAI_API_KEY = st.secrets["OPENAI_API_KEY"]
except:
    # Fallback for local development
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
    if not OPENAI_API_KEY:
        st.error("⚠️ OpenAI API key not found. Please configure it in Streamlit secrets.")
        st.stop()

client = OpenAI(api_key=OPENAI_API_KEY)

# Page configuration
st.set_page_config(
    page_title="Financial AI Assistant",
    page_icon="💰",
    layout="wide"
)

# Initialize session state
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
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

Each transaction is a Python dataclass with these attributes (use DOT notation to access):
- transaction.date (string, YYYY-MM-DD): Transaction date
- transaction.account (string): Account identifier (User ID)
- transaction.category (string): User-defined transaction type (e.g., 'Food', 'Leisure')
- transaction.merchant (string): Merchant name (e.g., 'AMAZON', 'APPLE')
- transaction.transaction_type (string): Either 'income' or 'outcome'
- transaction.currency (string): Currency code (e.g., 'USD', 'EUR', 'GBP')
- transaction.amount (float): Amount in original currency (non-negative)
- transaction.amount_uc (float): Amount in user's default currency (non-negative)

CRITICAL: Access attributes using DOT notation: transaction.date, transaction.amount
NEVER use bracket notation: transaction['date'] will cause errors!

IMPORTANT: Filter transactions by current user ID: {current_user_id}
Always filter: user_transactions = [t for t in transaction_list if t.account == '{current_user_id}']

Example correct code:
```python
def get_context(transaction_list):
    import datetime
    # Filter by current user
    user_transactions = [t for t in transaction_list if t.account == '{current_user_id}']
    
    total = 0
    for transaction in user_transactions:
        if transaction.transaction_type == 'outcome':
            total += transaction.amount_uc
    return {{'total': total}}
```

*Task*
Generate a response in JSON format with these keys:

1. "is_relevant": (Boolean) True if query is about financial transactions, False otherwise.
2. "needs_diagram": (Boolean) True if query requires visualization (comparisons, trends over time).
3. "context_code": (String) Python function named `get_context` that processes transaction_list.
   - MUST filter by user ID first: [t for t in transaction_list if t.account == '{current_user_id}']
   - Must use DOT notation to access transaction attributes
   - Returns a dictionary with necessary context for answering AND for plotting
   - For plots, include data as lists: {{'labels': ['Dec', 'Jan'], 'values': [1000, 800]}}
4. "algorithm_explanation": (String) High-level explanation in '{user_language}'.
5. "diagram_code": (String) ONLY if needs_diagram is True. Python function named `plot` that:
   - Takes context dictionary as parameter
   - Uses ONLY plotly.express (import as px) or plotly.graph_objects (import as go)
   - NEVER use matplotlib or seaborn
   - Creates and returns a plotly figure object
   - Common chart types:
     * Bar chart: px.bar(x=context['labels'], y=context['values'], title='Title')
     * Line chart: px.line(x=context['dates'], y=context['amounts'], title='Title')
     * Pie chart: px.pie(values=context['values'], names=context['labels'], title='Title')
   - Example bar chart:
   ```python
   def plot(context):
       import plotly.express as px
       fig = px.bar(
           x=context['labels'], 
           y=context['values'],
           title='Spending Comparison',
           labels={{'x': 'Month', 'y': 'Amount'}}
       )
       return fig
   ```
   - Example with graph_objects:
   ```python
   def plot(context):
       import plotly.graph_objects as go
       fig = go.Figure(data=[
           go.Bar(x=context['labels'], y=context['values'], marker_color='lightblue')
       ])
       fig.update_layout(
           title='Spending by Category',
           xaxis_title='Category',
           yaxis_title='Amount',
           template='plotly_white'
       )
       return fig
   ```

*Input Context*:
  * Current User ID: {current_user_id}
  * Current date: {latest_date}
  * Date range: {start_date} to {latest_date}
  * User's default currency: '{currency}'
  * User's default language: '{user_language}'
  * User's Categories: {unique_categories}
  * User's Currencies: {unique_currencies}

Query: {question}

*CRITICAL Requirements*:
- ALWAYS filter by user ID first in get_context function
- Use DOT notation: transaction.date, transaction.amount_uc, etc.
- For plotting: ONLY use plotly.express or plotly.graph_objects
- NEVER import or use matplotlib, seaborn, or pyplot
- Import only: datetime, plotly.express as px, plotly.graph_objects as go (if needed)
- Function names must be exactly: get_context and plot
- The plot function MUST return a plotly figure object
- If query is irrelevant or dates out of range, return:
  {{"is_relevant": false,"needs_diagram": false,"context_code": "","algorithm_explanation":"","diagram_code": ""}}

Return valid JSON string. Remember: Use ONLY Plotly for charts, NEVER matplotlib!
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

def load_baseline_dataset():
    """Load the baseline transaction dataset"""
    try:
        # Try to load from file
        df = pd.read_csv('test_input.csv')
        return df
    except FileNotFoundError:
        st.error("❌ Baseline dataset 'test_input.csv' not found. Please ensure the file is in the same directory as the app.")
        return None

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

def run_prompt(prompt, system_message, output_format):
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

def process_question(question, transaction_list, local_info, current_user_id):
    """Process user question and generate response"""
    
    # Filter transactions for current user only
    user_transactions = [t for t in transaction_list if t.account == current_user_id]
    
    if not user_transactions:
        return f"No transactions found for user ID: {current_user_id}", None, None
    
    # Extract metadata from user's transactions only
    unique_categories = str(set(t.category for t in user_transactions))
    unique_currencies = str(set(t.currency for t in user_transactions))
    
    # Generate code
    system_message = "You are a helpful assistant that generates Python code for financial data analysis."
    full_prompt = PROMPT_CONTEXT_PYTHON.format(
        question=question,
        current_user_id=current_user_id,
        unique_categories=unique_categories,
        unique_currencies=unique_currencies,
        **local_info
    )
    
    code_response = run_prompt(full_prompt, system_message, 'json')
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
        with st.expander("🐛 See generated code"):
            st.code(code_dict['context_code'])
        return None, None, None
    
    # Generate natural language output
    system_message = "You are a helpful financial assistant."
    output_prompt = PROMPT_OUTPUT.format(
        question=question,
        context=context,
        **local_info
    )
    
    output = run_prompt(output_prompt, system_message, 'text')
    
    # Handle diagram if needed
    fig = None
    if code_dict.get('needs_diagram', False) and code_dict.get('diagram_code'):
        try:
            exec(code_dict['diagram_code'], globals())
            fig = plot(context)
        except Exception as e:
            st.warning(f"Could not generate diagram: {str(e)}")
            with st.expander("🐛 See diagram code"):
                st.code(code_dict.get('diagram_code', 'No code generated'))
    
    return output, context, fig

# Authentication/Setup Page
if not st.session_state.authenticated:
    st.title("💰 Financial AI Assistant")
    st.markdown("### Welcome! Please enter your details to get started")
    
    with st.form("user_setup"):
        col1, col2 = st.columns(2)
        
        with col1:
            user_id = st.text_input(
                "User ID *",
                value="d3f6dc6d-badb-4b8f-ae52-db4185c622f7",
                help="Your unique user identifier"
            )
            language = st.selectbox(
                "Language *",
                ["ENG", "RUS", "GEO"],
                index=0
            )
        
        with col2:
            country = st.selectbox(
                "Country *",
                ["USA", "GEO", "RUS", "GBR", "EUR"],
                index=0
            )
            currency = st.selectbox(
                "Default Currency *",
                ["USD", "GEL", "EUR", "GBP"],
                index=0
            )
        
        submitted = st.form_submit_button("Start Chatting", use_container_width=True)
        
        if submitted:
            if user_id:
                # Load baseline dataset
                with st.spinner("Loading transaction data..."):
                    df = load_baseline_dataset()
                    
                    if df is not None:
                        st.session_state.transaction_list = df_to_transaction_list(df)
                        
                        # Check if user exists in dataset
                        user_transactions = [t for t in st.session_state.transaction_list if t.account == user_id]
                        
                        if not user_transactions:
                            st.error(f"❌ User ID '{user_id}' not found in the dataset. Please check your ID.")
                        else:
                            # Extract date range from user's transactions
                            dates = [t.date for t in user_transactions]
                            start_date = min(dates)
                            latest_date = max(dates)
                            
                            st.session_state.local_info = {
                                'user_language': language,
                                'user_country': country,
                                'currency': currency,
                                'start_date': start_date,
                                'latest_date': latest_date
                            }
                            st.session_state.user_id = user_id
                            st.session_state.authenticated = True
                            st.rerun()
            else:
                st.error("Please enter your User ID")

# Main Chat Interface
else:
    # Header with user info
    col1, col2, col3 = st.columns([3, 1, 1])
    with col1:
        st.title("💰 Financial AI Assistant")
    with col2:
        st.metric("User", st.session_state.user_id[:8] + "...")
    with col3:
        if st.button("🔄 Change User", use_container_width=True):
            st.session_state.authenticated = False
            st.session_state.messages = []
            st.rerun()
    
    # Display transaction info
    user_transactions = [t for t in st.session_state.transaction_list if t.account == st.session_state.user_id]
    st.info(f"📊 Loaded {len(user_transactions)} transactions | 📅 {st.session_state.local_info['start_date']} to {st.session_state.local_info['latest_date']} | 💱 {st.session_state.local_info['currency']}")
    
    st.divider()
    
    # Chat interface
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if "context" in message and message["context"]:
                with st.expander("📊 See context data"):
                    st.json(message["context"])
            if "figure" in message and message["figure"]:
                st.plotly_chart(message["figure"], use_container_width=True)
    
    # Chat input
    if prompt := st.chat_input("Ask about your transactions..."):
        # Add user message
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)
        
        # Generate response
        with st.chat_message("assistant"):
            with st.spinner("Analyzing your transactions..."):
                response, context, fig = process_question(
                    prompt,
                    st.session_state.transaction_list,
                    st.session_state.local_info,
                    st.session_state.user_id
                )
                
                if response:
                    st.markdown(response)
                    
                    # Show context in expander
                    if context:
                        with st.expander("📊 See context data"):
                            st.json(context)
                    
                    # Show diagram if available
                    if fig:
                        st.plotly_chart(fig, use_container_width=True)
                    
                    # Save to chat history
                    st.session_state.messages.append({
                        "role": "assistant",
                        "content": response,
                        "context": context,
                        "figure": fig
                    })
                else:
                    st.error("Failed to generate response. Please try again.")

# Footer
st.divider()
st.markdown("""
<div style='text-align: center; color: gray;'>
    <small>Built with Streamlit & OpenAI | Analyzing your personal financial data</small>
</div>
""", unsafe_allow_html=True)
