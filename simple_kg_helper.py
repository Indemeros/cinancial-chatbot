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
        question_lower = question.lower()
        kg_keywords = ['сравни', 'compare', 'топ', 'top', 'часто']
        return any(keyword in question_lower for keyword in kg_keywords)
    
    def query_kg(self, question, user_id, currency):
        cypher_prompt = f"""Generate Cypher for Neo4j.
Schema: (Transaction)-[:MADE_AT]->(Merchant), (Transaction)-[:BELONGS_TO]->(Category), (Transaction)-[:FROM_ACCOUNT]->(Account)
Question: {question}
User ID: {user_id}
Return JSON: {{"cypher": "...", "parameters": {{"user_id": "{user_id}"}}}}"""
        
        try:
            response = self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": cypher_prompt}],
                temperature=0,
                response_format={"type": "json_object"}
            )
            result = json.loads(response.choices[0].message.content)
            cypher = result.get('cypher')
            parameters = result.get('parameters', {'user_id': user_id})
            
            if cypher:
                with self.driver.session() as session:
                    records = session.run(cypher, parameters)
                    data = [record.data() for record in records]
                return {'cypher': cypher, 'results': data, 'parameters': parameters}
        except Exception as e:
            st.error(f"KG error: {e}")
        return None
    
    def format_kg_results(self, kg_data, question, language, currency):
        if not kg_data or not kg_data.get('results'):
            return "Данные не найдены." if language == 'RUS' else "No data found."
        try:
            response = self.openai.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": f"Question: {question}\nResults: {kg_data['results']}\nLanguage: {language}"}],
                temperature=0.3
            )
            return response.choices[0].message.content.strip()
        except:
            return str(kg_data['results'])