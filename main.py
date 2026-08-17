import re
import pandas as pd
from langchain_ollama.llms import OllamaLLM
from langchain_core.prompts import ChatPromptTemplate
from vector import retriever

# Load pandas dataframe into memory once for fast analytical queries
df = pd.read_excel("products_cleaned.xlsx")
df['Price_num'] = pd.to_numeric(df['Price'], errors='coerce')

model = OllamaLLM(model="llama3.1")

# Fast translation chain using Llama 3.1
translation_prompt = ChatPromptTemplate.from_template(
    "Translate the following user query into concise English. "
    "If it is already in English, return it unchanged. Output ONLY the translation.\n\nQuery: {query}"
)
translator_chain = translation_prompt | model

def handle_structured_query(english_query: str, category: str = None):
    query_lower = english_query.lower().strip()
    
    # -------------------------------------------------------------
    # 1. PRICE THRESHOLD DETECTION
    # -------------------------------------------------------------
    price_match = re.search(r'(?:lower than|under|less than|below|<)\s*(\d+)', query_lower)
    max_price = float(price_match.group(1)) if price_match else None

    min_match = re.search(r'(?:higher than|more than|above|over|greater than|>)\s*(\d+)', query_lower)
    min_price = float(min_match.group(1)) if min_match else None

    # Determine active category context
    active_cat = category
    if any(w in query_lower for w in ["laptop", "notebook", "computer"]):
        active_cat = "laptop"
    elif any(w in query_lower for w in ["antivirus", "virus", "security", "protection"]):
        active_cat = "antivirus"
    elif any(w in query_lower for w in ["firewall", "router", "networking"]):
        active_cat = "firewall"

    # -------------------------------------------------------------
    # 2. PRICE LOOKUP QUERY
    # -------------------------------------------------------------
    if any(phrase in query_lower for phrase in ["how much", "price of", "cost of"]) and not max_price and not min_price:
        search_terms = re.sub(r'how much is|how much|price of|cost of|is the|a|an', '', query_lower).strip()
        
        if len(search_terms) > 2:
            matches = df[
                df["Title"].astype(str).str.contains(search_terms, case=False, na=False) |
                df["Vendor"].astype(str).str.contains(search_terms, case=False, na=False)
            ].sort_values(by="Price_num", ascending=True)
            
            if not matches.empty:
                results = []
                for idx, row in matches.head(5).iterrows():
                    results.append(f"• {row['Title']} — Price: {row['Price_num']:,.2f} THB (Vendor: {row['Vendor']})")
                return "\n".join(results)

    # -------------------------------------------------------------
    # 3. RANKING / THRESHOLD / RECOMMENDATION LOGIC
    # -------------------------------------------------------------
    is_ranking = any(word in query_lower for word in ["top", "cheapest", "expensive", "highest", "lowest", "most", "best", "recommend", "recommand"])
    
    if is_ranking or max_price is not None or min_price is not None:
        # Extract explicit count limit (e.g. "top 5"), ignore price numbers in 'n' extraction
        clean_query_for_num = re.sub(r'(?:lower than|under|less than|below|<|higher than|more than|above|over|greater than|>)\s*\d+', '', query_lower)
        match = re.search(r'\b(\d+)\b', clean_query_for_num)
        n = int(match.group(1)) if match else 5
        
        # Sort ascending unless explicitly asking for expensive/highest
        is_ascending = not any(word in query_lower for word in ["expensive", "highest", "most"])
        
        filtered_df = df.dropna(subset=['Price_num']).copy()

        # Apply strict category mask to filter out All-in-Ones, Monitors, and Desktops
        if active_cat == "laptop":
            category_mask = (
                filtered_df["Title"].astype(str).str.contains("laptop|notebook|expertbook|latitude|thinkpad|thinkbook|travelmate|macbook", case=False, na=False) |
                filtered_df["Vendor"].astype(str).str.contains("Notebook & PC", case=False, na=False)
            )
            exclude_mask = ~filtered_df["Title"].astype(str).str.contains("monitor|display|optiplex|thinkvision|aio|all-in-one|sff|m70a|v50a", case=False, na=False)
            filtered_df = filtered_df[category_mask & exclude_mask]
            
        elif active_cat == "antivirus":
            category_mask = (
                filtered_df["Title"].astype(str).str.contains("antivirus|falcon|sentinelone|sophos|security|crowdstrike|singularity", case=False, na=False) |
                filtered_df["Product Category"].astype(str).str.contains("Antivirus|Security", case=False, na=False)
            )
            filtered_df = filtered_df[category_mask]
            
        elif active_cat == "firewall":
            category_mask = filtered_df["Title"].astype(str).str.contains("fortigate|sophos|sonicwall|watchguard|firewall", case=False, na=False)
            filtered_df = filtered_df[category_mask]

        # Apply Numerical Thresholds strictly
        if max_price is not None:
            filtered_df = filtered_df[filtered_df["Price_num"] < max_price]
        if min_price is not None:
            filtered_df = filtered_df[filtered_df["Price_num"] > min_price]

        top_df = filtered_df.sort_values(by="Price_num", ascending=is_ascending).head(n)
        
        if top_df.empty:
            return "No matching products found in the database matching your criteria."

        results = []
        for idx, row in top_df.iterrows():
            results.append(f"• {row['Title']} — Price: {row['Price_num']:,.2f} THB")
        return "\n".join(results)
    
    return None

template = """
You are an intelligent sales assistant for Monster Connect (mon.co.th).

Use ONLY the retrieved products below to answer the user's question clearly and accurately.
If you cannot find the exact product, politely inform the user.
Answer in the same language the user used in their original question (ENGLISH ONLY).

Products:
{products}

Question:
{question}
"""

prompt = ChatPromptTemplate.from_template(template)
chain = prompt | model

# Active session state tracker
current_category = None

print("--- Monster Connect Intelligent Assistant Ready ---")

while True:
    question = input("\nAsk your question (q to quit): ").strip()

    if not question:
        continue
    if question.lower() == "q":
        break

    # 1. Translate query to English for internal routing & filtering
    translated_query = translator_chain.invoke({"query": question}).strip()
    query_lower = translated_query.lower()

    # 2. Update category memory state
    if any(w in query_lower for w in ["laptop", "notebook", "computer"]):
        current_category = "laptop"
    elif any(w in query_lower for w in ["antivirus", "security", "protection"]):
        current_category = "antivirus"
    elif any(w in query_lower for w in ["firewall", "router"]):
        current_category = "firewall"

    # 3. Process structured query using translated query and active memory
    structured_response = handle_structured_query(translated_query, category=current_category)
    
    if structured_response:
        print("\nAI Answer (Data Engine):\n")
        print(f"Here are the requested items matching your criteria:\n\n{structured_response}")
    else:
        # 4. Fall back to Vector RAG for descriptive queries
        docs = retriever.invoke(question)
        context = "\n\n".join([doc.page_content for doc in docs])
        
        result = chain.invoke({
            "products": context,
            "question": question
        })
        print("\nAI Answer (RAG Engine):\n")
        print(result)