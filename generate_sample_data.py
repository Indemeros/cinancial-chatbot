"""
Simple Knowledge Graph Integration
Exact Schema: Transaction -> Merchant/Category/Account
"""

from neo4j import GraphDatabase
from openai import OpenAI
import json
import streamlit as st


class SimpleKGHelper:
    """Helper to query Neo4j only when needed"""
    
    def __init__(self, uri: str, user: str, password: str, openai_client: OpenAI):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.openai = openai_client
    
    def close(self):
        self.driver.close()
    
    def should_use_kg(self, question: str) -> bool:
        """
        Decide if question needs KG or can use simple processing
        """
    
    def query_kg(self, question: str, user_id: str, currency: str) -> dict:
        """
        Ask GPT to generate Cypher, then query Neo4j
        """
        
        # Step 1: Generate Cypher query
        cypher_prompt = f"""Generate a Cypher query for Neo4j.

EXACT Schema (use these exact relationship names):
- (Transaction) node with properties: id, date, amount, amount_uc, type
- (Merchant) node with properties: name
- (Category) node with properties: name  
- (Account) node with properties: id
- (Transaction)-[:MADE_AT]->(Merchant)
- (Transaction)-[:BELONGS_TO]->(Category)
- (Transaction)-[:FROM_ACCOUNT]->(Account)

Current User: Account.id = "{user_id}"
Currency: {currency}

Question: {question}

IMPORTANT:
- To filter by user: MATCH (t:Transaction)-[:FROM_ACCOUNT]->(a:Account {{id: $user_id}})
- For totals use: sum(t.amount_uc)
- For Russian categories like "Еда вне дома" or "Продукты", use exact name match
- Return results with descriptive column names

Return ONLY valid JSON:
{{
  "cypher": "MATCH ... WHERE ... RETURN ...",
  "parameters": {{"user_id": "{user_id}"}}
}}
"""
        
        try:
            response = self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a Cypher expert. Return only JSON."},
                    {"role": "user", "content": cypher_prompt}
                ],
                temperature=0,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            cypher = result.get('cypher')
            parameters = result.get('parameters', {'user_id': user_id})
            
            if not cypher:
                return None
            
            # Step 2: Execute Cypher
            with self.driver.session() as session:
                records = session.run(cypher, parameters)
                data = [record.data() for record in records]
            
            return {
                'source': 'kg',
                'cypher': cypher,
                'parameters': parameters,
                'results': data
            }
            
        except Exception as e:
            st.error(f"KG query failed: {e}")
            return None
    
    def format_kg_results(self, kg_data: dict, question: str, language: str, currency: str) -> str:
        """Convert KG results to natural language"""
        
        if not kg_data or not kg_data.get('results'):
            return "Данные не найдены." if language == 'RUS' else "No data found."
        
        format_prompt = f"""Convert these query results to a natural answer.

Question: {question}
Results: {json.dumps(kg_data['results'], ensure_ascii=False)}

Language: {language}
Currency: {currency}

Be concise and conversational.
"""
        
        try:
            response = self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a helpful financial assistant."},
                    {"role": "user", "content": format_prompt}
                ],
                temperature=0.3
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            return str(kg_data['results'])


# =============================================================================
# INTEGRATION INTO YOUR APP.PY
# =============================================================================

"""
Add this to your app.py:

1. Import at top:
   from simple_kg_helper import SimpleKGHelper

2. After user authentication (around line 260):
   if 'kg' not in st.session_state:
       try:
           st.session_state.kg = SimpleKGHelper(
               uri=st.secrets["neo4j"]["uri"],
               user=st.secrets["neo4j"]["username"],
               password=st.secrets["neo4j"]["password"],
               openai_client=client
           )
       except:
           st.session_state.kg = None

3. Replace process_question call (around line 380):
   
   # Check if KG should be used
   if st.session_state.kg and st.session_state.kg.should_use_kg(prompt):
       st.caption("🔍 Using Knowledge Graph")
       
       # Query KG
       kg_data = st.session_state.kg.query_kg(
           question=prompt,
           user_id=st.session_state.user_id,
           currency=st.session_state.local_info['currency']
       )
       
       if kg_data:
           # Format results
           response = st.session_state.kg.format_kg_results(
               kg_data, prompt,
               st.session_state.local_info['user_language'],
               st.session_state.local_info['currency']
           )
           context = kg_data
           fig = None
           
           # Show Cypher query
           with st.expander("🔧 Cypher Query"):
               st.code(kg_data['cypher'], language='cypher')
               st.json(kg_data['parameters'])
       else:
           # Fallback to simple processing
           response, context, fig = process_question(
               prompt, st.session_state.transaction_list,
               st.session_state.local_info, st.session_state.user_id
           )
   else:
       st.caption("🔍 Using In-Memory Processing")
       # Use your existing simple processing
       response, context, fig = process_question(
           prompt, 
           st.session_state.transaction_list,
           st.session_state.local_info,
           st.session_state.user_id
       )

4. Add to secrets (.streamlit/secrets.toml):
   [neo4j]
   uri = "bolt://localhost:7687"
   username = "neo4j"
   password = "your_password"
"""

# =============================================================================
# EXAMPLE CYPHER QUERIES (for reference)
# =============================================================================

"""
Example 1: Compare two categories
MATCH (t:Transaction)-[:FROM_ACCOUNT]->(a:Account {id: $user_id})
MATCH (t)-[:BELONGS_TO]->(c:Category)
WHERE c.name IN ['Еда вне дома', 'Продукты']
RETURN c.name as category, sum(t.amount_uc) as total
ORDER BY total DESC

Example 2: Top merchants
MATCH (t:Transaction)-[:FROM_ACCOUNT]->(a:Account {id: $user_id})
MATCH (t)-[:MADE_AT]->(m:Merchant)
RETURN m.name as merchant, sum(t.amount_uc) as total, count(t) as visits
ORDER BY total DESC
LIMIT 5

Example 3: Category breakdown
MATCH (t:Transaction)-[:FROM_ACCOUNT]->(a:Account {id: $user_id})
MATCH (t)-[:BELONGS_TO]->(c:Category)
WHERE t.type = 'outcome'
RETURN c.name as category, sum(t.amount_uc) as total
ORDER BY total DESC
"""
        
        try:
            response = self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a Cypher expert. Return only JSON."},
                    {"role": "user", "content": cypher_prompt}
                ],
                temperature=0,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            cypher = result.get('cypher')
            parameters = result.get('parameters', {'user_id': user_id})
            
            if not cypher:
                return None
            
            # Step 2: Execute Cypher
            with self.driver.session() as session:
                records = session.run(cypher, parameters)
                data = [record.data() for record in records]
            
            return {
                'source': 'kg',
                'cypher': cypher,
                'results': data
            }
            
        except Exception as e:
            st.error(f"KG query failed: {e}")
            return None
    
    def format_kg_results(self, kg_data: dict, question: str, language: str, currency: str) -> str:
        """Convert KG results to natural language"""
        
        if not kg_data or not kg_data.get('results'):
            return "Данные не найдены." if language == 'RUS' else "No data found."
        
        format_prompt = f"""Convert these query results to a natural answer.

Question: {question}
Results: {json.dumps(kg_data['results'], ensure_ascii=False)}

Language: {language}
Currency: {currency}

Be concise and conversational.
"""
        
        try:
            response = self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a helpful financial assistant."},
                    {"role": "user", "content": format_prompt}
                ],
                temperature=0.3
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            return str(kg_data['results'])


# =============================================================================
# INTEGRATION INTO YOUR APP.PY
# =============================================================================

"""
Add this to your app.py:

1. Import at top:
   from simple_kg_helper import SimpleKGHelper

2. After user authentication:
   if 'kg' not in st.session_state:
       try:
           st.session_state.kg = SimpleKGHelper(
               uri=st.secrets["neo4j"]["uri"],
               user=st.secrets["neo4j"]["username"],
               password=st.secrets["neo4j"]["password"],
               openai_client=client
           )
       except:
           st.session_state.kg = None

3. In your chat processing (replace process_question call):
   
   # Check if KG should be used
   if st.session_state.kg and st.session_state.kg.should_use_kg(prompt):
       st.caption("🔍 Using Knowledge Graph")
       
       # Query KG
       kg_data = st.session_state.kg.query_kg(
           question=prompt,
           user_id=st.session_state.user_id,
           currency=st.session_state.local_info['currency']
       )
       
       if kg_data:
           # Format results
           response = st.session_state.kg.format_kg_results(
               kg_data, prompt,
               st.session_state.local_info['user_language'],
               st.session_state.local_info['currency']
           )
           context = kg_data
           fig = None
           
           # Show Cypher query
           with st.expander("🔧 Cypher Query"):
               st.code(kg_data['cypher'], language='cypher')
       else:
           # Fallback to simple processing
           response, context, fig = process_question(...)
   else:
       st.caption("🔍 Using In-Memory Processing")
       # Use your existing simple processing
       response, context, fig = process_question(
           prompt, 
           st.session_state.transaction_list,
           st.session_state.local_info,
           st.session_state.user_id
       )

4. Add to secrets (.streamlit/secrets.toml):
   [neo4j]
   uri = "bolt://localhost:7687"
   username = "neo4j"
   password = "your_password"
"""

# =============================================================================
# EXAMPLE QUERIES
# =============================================================================

"""
SIMPLE (uses existing code):
- "Сколько я потратил в январе?"
- "Когда я платил Amazon?"

COMPLEX (uses KG):
- "Сравни мои затраты на еду вне дома и продукты"
- "Топ 5 магазинов по расходам"
- "В каких категориях я трачу больше всего?"
"""