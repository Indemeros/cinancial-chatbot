"""
Simple Knowledge Graph Integration
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
        """Decide if question needs KG"""
        question_lower = question.lower()
        kg_keywords = [
            'сравни', 'compare', 'vs', 'versus',
            'топ', 'top', 'больше всего', 'most',
            'часто', 'обычно', 'предпочитаю', 'often', 'usually'
        ]
        return any(keyword in question_lower for keyword in kg_keywords)
    
    def query_kg(self, question: str, user_id: str, currency: str) -> dict:
        """Generate Cypher and query Neo4j"""
        
        cypher_prompt = f"""Generate a Cypher query for Neo4j.

EXACT Schema:
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