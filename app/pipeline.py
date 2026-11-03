from app.llm.sql_generator import generate_sql
from app.sql.executor import execute_sql


def run_pipeline(question: str):
    """
    Run the complete natural-language-to-SQL workflow.
    """

    if not question or not question.strip():
        raise ValueError("Please enter a business question.")

    print("\n1. Generating SQL with Gemini...", flush=True)
    generated_sql = generate_sql(question)

    print("\n2. Generated SQL:")
    print(generated_sql)

    print("\n3. Validating and executing SQL...", flush=True)
    results = execute_sql(generated_sql)

    print("\n4. Pipeline completed successfully.", flush=True)

    return generated_sql, results


if __name__ == "__main__":

    question = "Show me the top 10 product categories by sales."

    try:
        sql, dataframe = run_pipeline(question)

        print("\nFINAL RESULTS:")
        print(dataframe.to_string(index=False))

    except Exception as error:
        print(f"\nPipeline failed: {error}")
