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
- Category hierarchy questions

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
        """Generate Cypher and query Neo4j with NEW SCHEMA"""
        
        cypher_prompt = f"""
⚠️⚠️⚠️ CRITICAL SCHEMA WARNING ⚠️⚠️⚠️
THIS SCHEMA HAS CHANGED! DO NOT USE OLD PATTERNS!
- NO Account nodes exist
- NO from_account properties exist  
- NO [:FROM_ACCOUNT] relationships exist
- NO [:MADE_AT] relationships exist
ONLY use the exact relationships listed below!

**Introduction**
You are an expert Cypher query generator for Neo4j graph database. Your task is to convert natural language questions about financial transactions into accurate, efficient Cypher queries.

**Graph Schema (EXACT structure - NEW SCHEMA)**

Nodes:
1. User
   - Properties: id (string), name (string - UUID)
   - Represents user accounts

2. Transaction
   - Properties: id (string), name (string - transaction ID like 'T1'), date (string), transaction_type (string: 'income' or 'outcome'), currency (string), amount (string), amount_uc (string - unified currency amount)
   - This is the CENTRAL node connecting all entities

3. Merchant
   - Properties: id (string), name (string)
   - Represents vendors/payees

4. Category
   - Properties: id (string), name (string)
   - User-defined spending categories (e.g., 'Продукты', 'Кафе и рестораны', 'Такси')
   - Has parent-child hierarchy for grouping

Relationships (use EXACT names - DO NOT USE ANY OTHER NAMES):
- (User)-[:MADE_TRANSACTION]->(Transaction)  ⚠️ NOT [:FROM_ACCOUNT], NOT [:MADE_BY]
- (Transaction)-[:AT_MERCHANT]->(Merchant)  ⚠️ NOT [:MADE_AT], NOT [:TO_MERCHANT]
- (Transaction)-[:IN_CATEGORY]->(Category)  ⚠️ NOT [:BELONGS_TO] for transactions
- (Merchant)-[:BELONGS_TO]->(Category)
- (Category)-[:BELONGS_TO]->(Category) [for hierarchy - child to parent]

⚠️ CRITICAL: There is NO Account node. There is NO from_account property. ONLY use User node!

**CRITICAL RULES - READ CAREFULLY**

1. USER FILTERING (MANDATORY):
   - ⚠️ THERE IS NO ACCOUNT NODE IN THIS SCHEMA
   - ⚠️ THERE IS NO from_account OR account_id PROPERTY
   - ⚠️ DO NOT USE [:FROM_ACCOUNT] - IT DOES NOT EXIST
   - CORRECT PATTERN: MATCH (u:User {{id: $user_id}})-[:MADE_TRANSACTION]->(t:Transaction)
   - WRONG: (t:Transaction)-[:FROM_ACCOUNT]->(a:Account)
   - WRONG: WHERE t.account_id = $user_id
   - WRONG: WHERE t.from_account = $user_id
   - Every query MUST start with User node and traverse via MADE_TRANSACTION

2. PROPERTY NAMES:
   - Use toFloat(t.amount_uc) for monetary totals (user's default currency)
   - Use toFloat(t.amount) for original transaction amounts
   - Use t.transaction_type for transaction type ('income' or 'outcome')
   - Use t.date for dates (stored as string 'YYYY-MM-DD')
   - IMPORTANT: amount and amount_uc are stored as STRINGS, use toFloat() to convert

3. AGGREGATIONS:
   - For totals: sum(toFloat(t.amount_uc))
   - For counts: count(t)
   - For averages: avg(toFloat(t.amount_uc))
   - Always convert strings to float for calculations

4. FILTERING:
   - For expenses only: WHERE t.transaction_type = 'outcome'
   - For income only: WHERE t.transaction_type = 'income'
   - For date ranges: WHERE t.date >= '2022-09-01' AND t.date <= '2023-02-28'

5. SORTING AND LIMITS:
   - Use ORDER BY for rankings (DESC for highest first)
   - Include LIMIT when asked for "top N" or "best"
   - Default to DESC for monetary amounts

6. CATEGORY NAMES:
   - Russian categories must match EXACTLY as stored
   - Common categories: 'Продукты', 'Кафе и рестораны', 'Такси', 'Лекарства', 'Овощи и фрукты'
   - Use c.name IN ['Cat1', 'Cat2'] for multiple categories
   - Case-sensitive matching

7. MERCHANT RELATIONSHIPS:
   - Merchants are linked to categories: (m:Merchant)-[:BELONGS_TO]->(c:Category)
   - You can navigate from Transaction to Merchant to Category
   - IMPORTANT: To filter by transaction category, use (t)-[:IN_CATEGORY]->(c:Category)
   - To filter by merchant's typical category, use (m)-[:BELONGS_TO]->(c:Category)
   - Most queries about "spending in category X" should filter transactions, not merchants!

8. CATEGORY HIERARCHY:
   - Parent categories exist (e.g., 'Еда и напитки' contains 'Продукты', 'Кафе и рестораны')
   - To get all transactions in a parent category:
     MATCH (child:Category)-[:BELONGS_TO]->(parent:Category {{name: 'Еда и напитки'}})
     MATCH (t:Transaction)-[:IN_CATEGORY]->(child)

9. RETURN CLAUSE:
   - Use descriptive aliases: AS total, AS merchant, AS category, AS count
   - Format for readability
   - Return only necessary columns

**Input Context**
- Current User ID: {user_id}
- User's Default Currency: {currency}
- Question: "{question}"

⚠️ SCHEMA REMINDER: Start EVERY query with:
MATCH (u:User {{id: $user_id}})-[:MADE_TRANSACTION]->(t:Transaction)
Then continue with -[:AT_MERCHANT]->(m:Merchant) or -[:IN_CATEGORY]->(c:Category) as needed.

**Task**
Generate a Cypher query that:
1. Answers the user's question accurately
2. Filters by the current user (MANDATORY)
3. Uses proper aggregations and sorting
4. Converts string amounts to float using toFloat()
5. Returns results with clear column names
6. Handles Russian text correctly

**Output Format**
Return ONLY valid JSON (no markdown, no explanations):
{{
  "cypher": "MATCH (u:User {{id: $user_id}})-[:MADE_TRANSACTION]->(t:Transaction) ...",
  "parameters": {{
    "user_id": "{user_id}"
  }}
}}

**Examples**

Example 1: "Топ 5 магазинов по расходам"
{{
  "cypher": "MATCH (u:User {{id: $user_id}})-[:MADE_TRANSACTION]->(t:Transaction)-[:AT_MERCHANT]->(m:Merchant) WHERE t.transaction_type = 'outcome' RETURN m.name AS merchant, sum(toFloat(t.amount_uc)) AS total_spent, count(t) AS visits ORDER BY total_spent DESC LIMIT 5",
  "parameters": {{
    "user_id": "{user_id}"
  }}
}}

Example 2: "Сравни мои затраты на 'Кафе и рестораны' и 'Продукты'"
{{
  "cypher": "MATCH (u:User {{id: $user_id}})-[:MADE_TRANSACTION]->(t:Transaction)-[:IN_CATEGORY]->(c:Category) WHERE c.name IN ['Кафе и рестораны', 'Продукты'] AND t.transaction_type = 'outcome' RETURN c.name AS category, sum(toFloat(t.amount_uc)) AS total_spent, count(t) AS transaction_count ORDER BY total_spent DESC",
  "parameters": {{
    "user_id": "{user_id}"
  }}
}}

Example 3: "Сколько транзакций у категории Такси?"
{{
  "cypher": "MATCH (u:User {{id: $user_id}})-[:MADE_TRANSACTION]->(t:Transaction)-[:IN_CATEGORY]->(c:Category {{name: 'Такси'}}) RETURN count(t) AS transaction_count, sum(toFloat(t.amount_uc)) AS total_amount",
  "parameters": {{
    "user_id": "{user_id}"
  }}
}}

Example 4: "Все мои расходы на еду" (using parent category)
{{
  "cypher": "MATCH (u:User {{id: $user_id}})-[:MADE_TRANSACTION]->(t:Transaction)-[:IN_CATEGORY]->(child:Category)-[:BELONGS_TO]->(parent:Category {{name: 'Еда и напитки'}}) WHERE t.transaction_type = 'outcome' RETURN child.name AS category, sum(toFloat(t.amount_uc)) AS total_spent ORDER BY total_spent DESC",
  "parameters": {{
    "user_id": "{user_id}"
  }}
}}

Example 5: "Топ 5 магазинов в категории Продукты" (merchants for specific transaction category)
{{
  "cypher": "MATCH (u:User {{id: $user_id}})-[:MADE_TRANSACTION]->(t:Transaction)-[:AT_MERCHANT]->(m:Merchant) MATCH (t)-[:IN_CATEGORY]->(c:Category {{name: 'Продукты'}}) WHERE t.transaction_type = 'outcome' RETURN m.name AS merchant, sum(toFloat(t.amount_uc)) AS total_spent, count(t) AS visits ORDER BY total_spent DESC LIMIT 5",
  "parameters": {{
    "user_id": "{user_id}"
  }}
}}

**Important Reminders**
- ALWAYS start with User node and filter by user_id
- Use toFloat() for amount and amount_uc in calculations
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
                    {"role": "system", "content": "You are a Cypher expert for Neo4j. CRITICAL: This graph has User nodes (NOT Account nodes). Relationships are [:MADE_TRANSACTION], [:AT_MERCHANT], [:IN_CATEGORY]. NO [:FROM_ACCOUNT] or [:MADE_AT] relationships exist. Always start queries with (u:User {id: $user_id})-[:MADE_TRANSACTION]->(t:Transaction). Return only valid JSON."},
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
            
            st.success(f"✅ Query generated: {cypher[:100]}...")
            
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
            import traceback
            st.code(traceback.format_exc())
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

Instructions:
- Be conversational and clear
- Format numbers with proper currency symbols
- Use the user's language
- Keep it concise but informative

Provide ONLY the answer, no additional commentary.
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