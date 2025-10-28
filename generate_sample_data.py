from neo4j import GraphDatabase
from openai import OpenAI
import json
import streamlit as st


class SimpleKGHelper:
    
    def __init__(self, uri, user, password, openai_client):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.openai = openai_client
    
    def close(self):
        self.driver.close()
    
    def should_use_kg(self, question):
        """Ask GPT if this query needs Knowledge Graph"""
        
        decision_prompt = f"""Decide if this question needs a graph database or simple processing.

Question: "{question}"

Use Graph Database if:
- Comparing multiple things (compare, vs, сравни)
- Finding top/best (top 5, most, больше всего, топ)
- Patterns (usually, often, frequently, часто, обычно)
- Complex multi-dimensional analysis

Use Simple Processing if:
- Basic totals (how much, total, сколько)
- Single lookups (when, where, когда)
- Simple filtering

Return JSON: {{"use_kg": true, "reasoning": "..."}} or {{"use_kg": false, "reasoning": "..."}}
"""
        
        try:
            st.info(f"🤖 Analyzing query complexity...")
            
            response = self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a query router. Return only valid JSON."},
                    {"role": "user", "content": decision_prompt}
                ],
                temperature=0,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            use_kg = result.get('use_kg', False)
            reasoning = result.get('reasoning', 'Unknown')
            
            if use_kg:
                st.success(f"✅ Using Knowledge Graph: {reasoning}")
            else:
                st.info(f"⚡ Using In-Memory: {reasoning}")
            
            return use_kg
            
        except Exception as e:
            st.error(f"❌ Routing failed: {str(e)}")
            st.warning("Defaulting to in-memory processing")
            return False
    
    def query_kg(self, question, user_id, currency):
        """Generate Cypher and query Neo4j with comprehensive instructions"""
        
        cypher_prompt = f"""
**Introduction**
You are an expert Cypher query generator for Neo4j graph database. Your task is to convert natural language questions about financial transactions into accurate, efficient Cypher queries.

**Graph Schema (EXACT structure)**

Nodes:
1. Transaction
   - Properties: id (string), date (date), amount (float), amount_uc (float), type (string: 'income' or 'outcome')
   - This is the CENTRAL node connecting all entities

2. Merchant
   - Properties: name (string)
   - Represents vendors/payees

3. Category
   - Properties: name (string)
   - User-defined spending categories (e.g., 'Еда вне дома', 'Продукты', 'Транспорт')

4. Account
   - Properties: id (string)
   - Represents user accounts

Relationships (use EXACT names):
- (Transaction)-[:MADE_AT]->(Merchant)
- (Transaction)-[:BELONGS_TO]->(Category)
- (Transaction)-[:FROM_ACCOUNT]->(Account)

**CRITICAL RULES - READ CAREFULLY**

1. USER FILTERING (MANDATORY):
   - Transaction node does NOT have a user_id property
   - You MUST filter by user using the FROM_ACCOUNT relationship
   - CORRECT: MATCH (t:Transaction)-[:FROM_ACCOUNT]->(a:Account {{id: $user_id}})
   - WRONG: WHERE t.user_id = $user_id
   - WRONG: WHERE t.account_id = $user_id
   - Every query MUST include user filtering via FROM_ACCOUNT

2. PROPERTY NAMES:
   - Use 't.amount_uc' for monetary totals (user's default currency)
   - Use 't.amount' for original transaction amounts
   - Use 't.type' for transaction type ('income' or 'outcome')
   - Use 't.date' for dates (stored as Neo4j date type)

3. AGGREGATIONS:
   - For totals: sum(t.amount_uc)
   - For counts: count(t)
   - For averages: avg(t.amount_uc)
   - Always use amount_uc for summations unless explicitly asked for original amounts

4. FILTERING:
   - For expenses only: WHERE t.type = 'outcome'
   - For income only: WHERE t.type = 'income'
   - For date ranges: WHERE t.date >= date('YYYY-MM-DD') AND t.date <= date('YYYY-MM-DD')

5. SORTING AND LIMITS:
   - Use ORDER BY for rankings (DESC for highest first)
   - Include LIMIT when asked for "top N" or "best"
   - Default to DESC for monetary amounts

6. CATEGORY NAMES:
   - Russian categories must match EXACTLY as stored
   - Common categories: 'Еда вне дома', 'Продукты', 'Транспорт', 'Развлечения'
   - Use c.name IN ['Cat1', 'Cat2'] for multiple categories
   - Case-sensitive matching

7. RETURN CLAUSE:
   - Use descriptive aliases: AS total, AS merchant, AS category, AS count
   - Format for readability
   - Return only necessary columns

**Input Context**
- Current User ID: {user_id}
- User's Default Currency: {currency}
- Question: "{question}"

**Task**
Generate a Cypher query that:
1. Answers the user's question accurately
2. Filters by the current user (MANDATORY)
3. Uses proper aggregations and sorting
4. Returns results with clear column names
5. Handles Russian text correctly

**Output Format**
Return ONLY valid JSON (no markdown, no explanations):
{{{{
  "cypher": "MATCH (t:Transaction)-[:FROM_ACCOUNT]->(a:Account {{id: $user_id}}) ...",
  "parameters": {{{{
    "user_id": "{user_id}"
  }}}}
}}}}

**Examples**

Example 1: "Топ 5 магазинов по расходам"
{{{{
  "cypher": "MATCH (t:Transaction)-[:FROM_ACCOUNT]->(a:Account {{id: $user_id}}) MATCH (t)-[:MADE_AT]->(m:Merchant) WHERE t.type = 'outcome' RETURN m.name AS merchant, SUM(t.amount_uc) AS total_spent, COUNT(t) AS visits ORDER BY total_spent DESC LIMIT 5",
  "parameters": {{{{
    "user_id": "{user_id}"
  }}}}
}}}}

Example 2: "Сравни мои затраты на 'Еда вне дома' и 'Продукты'"
{{{{
  "cypher": "MATCH (t:Transaction)-[:FROM_ACCOUNT]->(a:Account {{id: $user_id}}) MATCH (t)-[:BELONGS_TO]->(c:Category) WHERE c.name IN ['Еда вне дома', 'Продукты'] AND t.type = 'outcome' RETURN c.name AS category, SUM(t.amount_uc) AS total_spent, COUNT(t) AS transaction_count ORDER BY total_spent DESC",
  "parameters": {{{{
    "user_id": "{user_id}"
  }}}}
}}}}

Example 3: "Сколько транзакций у категории Транспорт?"
{{{{
  "cypher": "MATCH (t:Transaction)-[:FROM_ACCOUNT]->(a:Account {{id: $user_id}}) MATCH (t)-[:BELONGS_TO]->(c:Category {{name: 'Транспорт'}}) RETURN COUNT(t) AS transaction_count, SUM(t.amount_uc) AS total_amount",
  "parameters": {{{{
    "user_id": "{user_id}"
  }}}}
}}}}

**Important Reminders**
- NEVER forget user filtering via FROM_ACCOUNT
- Use sum(t.amount_uc) not sum(t.amount) for totals
- Match category names EXACTLY (case-sensitive, with Russian characters)
- Always return meaningful column aliases
- Test logic: does this query actually answer the question?

Now generate the Cypher query for the question above.
"""
        
        try:
            st.info("🔧 Generating Cypher query...")
            
            response = self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a Cypher expert. Return only valid JSON."},
                    {"role": "user", "content": cypher_prompt}
                ],
                temperature=0,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            cypher = result.get('cypher')
            parameters = result.get('parameters', {'user_id': user_id})
            
            if not cypher:
                st.error("No Cypher query generated")
                return None
            
            st.success(f"✅ Query generated: {cypher[:80]}...")
            
            # Execute query
            with self.driver.session() as session:
                records = session.run(cypher, parameters)
                data = [record.data() for record in records]
            
            st.success(f"✅ Retrieved {len(data)} records from Knowledge Graph")
            
            return {
                'source': 'kg',
                'cypher': cypher,
                'results': data,
                'parameters': parameters
            }
            
        except Exception as e:
            st.error(f"❌ KG query failed: {str(e)}")
            return None
    
    def format_kg_results(self, kg_data, question, language, currency):
        """Convert KG results to natural language"""
        
        if not kg_data or not kg_data.get('results'):
            return "Данные не найдены." if language == 'RUS' else "No data found."
        
        format_prompt = f"""Convert query results to a natural answer.

Question: {question}
Results: {json.dumps(kg_data['results'], ensure_ascii=False, indent=2)}
Language: {language}
Currency: {currency}

Be conversational and clear.
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
            st.error(f"Formatting failed: {e}")
            return str(kg_data['results'])