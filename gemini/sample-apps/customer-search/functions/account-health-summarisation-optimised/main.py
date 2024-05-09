# pylint: disable=E0401

from concurrent.futures import ThreadPoolExecutor
from os import environ
from typing import Dict

import functions_framework
from google.cloud import bigquery, storage
import vertexai
from vertexai.generative_models import FinishReason, GenerativeModel, Part
import vertexai.preview.generative_models as generative_models

client: bigquery.Client = bigquery.Client()


def run(name: str, statement: str) -> tuple[str, bigquery.table.RowIterator]:
    """
    Runs a BigQuery query and returns the name of the query and the result iterator.

    Args:
        name (str): The name of the query.
        statement (str): The BigQuery query statement.

    Returns:
        A tuple containing the name of the query and the result iterator.
    """

    return name, client.query(statement).result()  # blocks the thread


def run_all(statements: Dict[str, str]) -> Dict[str, bigquery.table.RowIterator]:
    """
    Runs multiple BigQuery queries in parallel and returns a dictionary of the results.

    Args:
        statements (Dict[str, str]): A dictionary of query names and statements.

    Returns:
        A dictionary of query names and result iterators.
    """

    with ThreadPoolExecutor() as executor:
        jobs = []
        for name, statement in statements.items():
            jobs.append(executor.submit(run, name, statement))
        result = dict([job.result() for job in jobs])
    return result


def upload_blob(
    bucket_name: str, source_file_name: str, destination_blob_name: str
) -> str:
    """
    Uploads a file to a Google Cloud Storage bucket.

    Args:
        bucket_name (str): The name of the bucket to upload the file to.
        source_file_name (str): The name of the file to upload.
        destination_blob_name (str): The name of the blob to create in the bucket.

    Returns:
        The public URL of the uploaded file.
    """

    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)

    blob = bucket.blob(destination_blob_name)
    blob.upload_from_string(source_file_name)
    print(f"File {source_file_name} uploaded to {destination_blob_name}.")
    return blob.public_url


def get_financial_details(
    query_str: str, value_str: str, res: Dict[str, bigquery.table.RowIterator]
) -> int:
    """
    Gets a financial detail from a BigQuery query result.

    Args:
        query_str (str): The name of the query that returned the result.
        value_str (str): The name of the value to get.
        res (Dict[str, bigquery.table.RowIterator]): The dictionary of query results.

    Returns:
        The financial detail as an integer.
    """

    for row in res[query_str]:
        if row[value_str] is not None:
            return int(row[value_str])
    return 0


@functions_framework.http
def account_health_summary(request):
    """
    Summarises the account health of a customer.

    Args:
        request (flask.Request): The request object.
            <https://flask.palletsprojects.com/en/1.1.x/api/#incoming-request-data>

    Returns:
        The response text, or any set of values that can be turned into a
        Response object using `make_response`
        <https://flask.palletsprojects.com/en/1.1.x/api/#flask.make_response>.
    """

    request_json = request.get_json(silent=True)

    client = bigquery.Client()

    customer_id = request_json["sessionInfo"]["parameters"]["cust_id"]

    if customer_id is not None:
        print("Customer ID ", customer_id)
    else:
        print("Customer ID not defined")

    project_id = environ.get("PROJECT_ID")
    query_check_cust_id = f"""
        SELECT EXISTS(SELECT * FROM `{project_id}.DummyBankDataset.Account` where customer_id = {customer_id}) as check
    """
    result_query_check_cust_id = client.query(query_check_cust_id)
    for row in result_query_check_cust_id:
        if row["check"] == 0:
            res = {
                "fulfillment_response": {
                    "messages": [
                        {
                            "text": {
                                "text": [
                                    "It seems you have entered an incorrect"
                                    " Customer ID. Please try again."
                                ]
                            }
                        }
                    ]
                }
            }
            return res

    query_assets = f"""
        SELECT sum(avg_monthly_bal) as asset FROM `{project_id}.DummyBankDataset.Account`
        where customer_id = {customer_id} and product in ('Savings A/C ', 'Savings Salary A/C ', 'Premium Current A/C ', 'Fixed Deposit', 'Flexi Deposit');
    """

    query_avg_monthly_balance = f"""
        SELECT sum(avg_monthly_bal) as avg_monthly_balance FROM `{project_id}.DummyBankDataset.Account`
        where customer_id = {customer_id} and product in ('Savings A/C ', 'Savings Salary A/C ', 'Premium Current A/C ');
    """

    query_fd = f"""
        SELECT sum(avg_monthly_bal) as asset FROM `{project_id}.DummyBankDataset.Account`
        where customer_id = {customer_id} and product = 'Fixed Deposit';
    """

    query_total_mf = f"""
        SELECT SUM(amount_invested) as total_mf_investment FROM `DummyBankDataset.MutualFundAccountHolding` where account_no in (
            select account_id from `DummyBankDataset.Account` where customer_id = {customer_id}
        );
    """

    query_high_risk_mf = f"""
        select SUM(amount_invested) as total_high_risk_investment from `DummyBankDataset.MutualFundAccountHolding` where risk_category > 4 and account_no in (
            select account_id from `DummyBankDataset.Account` where customer_id = {customer_id}
        )
    """

    query_debts = f"""
        SELECT sum(avg_monthly_bal) as debt FROM `{project_id}.DummyBankDataset.Account`
        where customer_id = {customer_id} and product in ('Gold Card','Medical Insurance','Premium Travel Card','Platinum Card','Personal Loan','Vehicle Loan','Consumer Durables Loan','Broking A/C');
    """

    query_account_details = f"""
        SELECT * FROM `{project_id}.DummyBankDataset.Account`
        WHERE customer_id = {customer_id}
    """

    query_user_details = f"""
        SELECT * FROM `{project_id}.DummyBankDataset.Customer`
        WHERE customer_id = {customer_id}
    """

    query_average_monthly_expense = f"""SELECT AVG(total_amount) as average_monthly_expense from (
        SELECT EXTRACT(MONTH FROM 	date) AS month,
        SUM(transaction_amount) AS total_amount FROM `{project_id}.DummyBankDataset.AccountTransactions` WHERE ac_id IN (SELECT account_id FROM `{project_id}.DummyBankDataset.Account` where customer_id = {customer_id})
        GROUP BY month
        ORDER BY month)
    """

    query_last_month_expense = f"""SELECT EXTRACT(MONTH FROM date) AS month,
    SUM(transaction_amount) AS last_month_expense FROM `{project_id}.DummyBankDataset.AccountTransactions` WHERE ac_id IN (SELECT account_id FROM `{project_id}.DummyBankDataset.Account` where customer_id={customer_id}) and EXTRACT(MONTH FROM date)=9
    GROUP BY month
    ORDER BY month;
    """

    query_investment_returns = f"""
        SELECT (amount_invested*one_month_return) as one_month_return, (amount_invested*TTM_Return) as TTM_Return,Scheme_Name from `{project_id}.DummyBankDataset.MutualFundAccountHolding`
        where account_no in (Select account_id from `{project_id}.DummyBankDataset.Account` where customer_id={customer_id})
    """

    res = run_all(
        {
            "query_assets": query_assets,
            "query_debts": query_debts,
            "query_account_details": query_account_details,
            "query_user_details": query_user_details,
            "query_fd": query_fd,
            "query_total_mf": query_total_mf,
            "query_high_risk_mf": query_high_risk_mf,
            "query_avg_monthly_balance": query_avg_monthly_balance,
            "query_average_monthly_expense": query_average_monthly_expense,
            "query_last_month_expense": query_last_month_expense,
            "query_investment_returns": query_investment_returns,
        }
    )

    scheme_name = []
    one_month_return = []
    ttm_return = []
    for row in res["query_investment_returns"]:
        scheme_name.append(row["Scheme_Name"])
        one_month_return.append(row["one_month_return"])
        ttm_return.append(row["TTM_Return"])

    asset_amount = get_financial_details(
        query_str="query_assets", value_str="asset", res=res
    )
    debt_amount = get_financial_details(
        query_str="query_debts", value_str="debt", res=res
    )
    total_income = 0
    total_expenditure = 0
    first_name = ""
    total_investment = 0
    total_high_risk_investment = 0
    avg_monthly_balance = get_financial_details(
        query_str="query_avg_monthly_balance", value_str="avg_monthly_balance", res=res
    )
    amount_transfered = ""
    account_status = ""
    average_monthly_expense = get_financial_details(
        query_str="query_average_monthly_expense",
        value_str="average_monthly_expense",
        res=res,
    )
    last_month_expense = get_financial_details(
        query_str="query_last_month_expense", value_str="last_month_expense", res=res
    )
    user_accounts = []

    for row in res["query_user_details"]:
        first_name = row["First_Name"]

    for row in res["query_account_details"]:
        user_accounts.append(row["account_id"])

    for account in user_accounts:
        query_transaction_details = f"""
            SELECT * FROM `{project_id}.DummyBankDataset.AccountTransactions`
            WHERE ac_id = {account}
        """

        query_expenditure_details = f"""
            SELECT SUM(transaction_amount) as expenditure FROM `{project_id}.DummyBankDataset.AccountTransactions` WHERE ac_id = {account} AND debit_credit_indicator = 'Debit'
        """

        query_income = f"""
            SELECT SUM(transaction_amount) as income FROM `{project_id}.DummyBankDataset.AccountTransactions` WHERE ac_id = {account} and debit_credit_indicator = 'Credit'
        """

        res_sub = run_all(
            {
                "query_transaction_details": query_transaction_details,
                "query_expenditure_details": query_expenditure_details,
                "query_income": query_income,
            }
        )
        for row in res_sub["query_income"]:
            if row["income"] is not None:
                total_income += row["income"]

        for row in res_sub["query_transaction_details"]:
            amount_transfered = (
                f"{amount_transfered},"
                f" {row['transaction_amount']} {row['description']}"
            )

        for row in res_sub["query_expenditure_details"]:
            if row["expenditure"] is not None:
                total_expenditure = total_expenditure + row["expenditure"]

    for row in res["query_fd"]:
        if row["asset"] is not None:
            total_investment += row["asset"]

    for row in res["query_total_mf"]:
        if row["total_mf_investment"] is not None:
            total_investment += row["total_mf_investment"]

    for row in res["query_high_risk_mf"]:
        if row["total_high_risk_investment"] is not None:
            total_high_risk_investment += row["total_high_risk_investment"]

    if (
        total_expenditure < 0.75 * total_income
        and asset_amount >= 0.2 * total_income
        and debt_amount < 0.3 * asset_amount
        and total_high_risk_investment < 0.3 * total_investment
    ):
        account_status = "Healthy"
    elif (
        (
            total_expenditure >= 0.75 * total_income
            and total_expenditure < 0.9 * total_income
        )
        or (asset_amount < 0.2 * total_income and asset_amount > 0.1 * total_income)
        or (debt_amount >= 0.3 * asset_amount and debt_amount < 0.75 * asset_amount)
        or (
            total_high_risk_investment >= 0.3 * total_investment
            and total_high_risk_investment < 0.8 * total_investment
        )
    ):
        account_status = "Needs Attention"
    else:
        account_status = "Concerning"

    vertexai.init(project=project_id, location="us-central1")
    generation_config = {
        "max_output_tokens": 2048,
        "temperature": 1,
        "top_p": 1,
    }
    safety_settings = {
        generative_models.HarmCategory.HARM_CATEGORY_HATE_SPEECH: generative_models.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
        generative_models.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: generative_models.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
        generative_models.HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: generative_models.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
        generative_models.HarmCategory.HARM_CATEGORY_HARASSMENT: generative_models.HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
    }
    model = model = GenerativeModel("gemini-1.0-pro-002")
    responses = model.generate_content(
        f"""You are a chatbot for bank application and you are required to briefly summarize the key insights of given numerical values in small pointers.
    You are provided with name, total income, total expenditure, total asset amount, total debt amount, total investment amount, high risk investments for the user in the following lines.
    {first_name},
    {total_income},
    {total_expenditure},
    {asset_amount},
    {debt_amount},
    {total_investment},
    {total_high_risk_investment},
    {avg_monthly_balance},
    {account_status},
    {scheme_name},
    {one_month_return},
    {ttm_return},

    Write in a professional and business-neutral tone.
    The summary should be in a conversation-like manner based on the Account Status.
    The summary should only be based on the information presented above.
    Avoid giving advice to the user for improving the Account Status, just include the information in short points.
    Don't comment on spendings of the person.
    The summary should be in pointers.
    The summary should fit in the word limit of 200.
    The summary for account health is for Name to read. So summary should be in second person's perespective tone.
    For example the summary must look like :
    - Your account status is Healthy.
    - Your current balance is ₹65,00,000.00.
    - Your income is ₹1,28,35,200.00 and your expenditure is ₹28,73,104.00.
    - You have a total asset of ₹5,65,00,000.00 and a total debt of ₹0.00.
    - You have invested ₹1,00,000.00 in high risk mutual funds.

    One_Month_Return and TTM_Return store the amounts in Indian currency, i.e., ₹.
    If Total Investment is greater than 0: the following details must be mentioned in a uniformly formatted table:
    For each element in Scheme_Name: mention the respective one month from One_Month_Return in ₹ and trailing twelve month returns from TTM_Return in ₹ in the table.
    """,
        generation_config=generation_config,
        safety_settings=safety_settings,
        stream=True,
    )

    final_response = ""
    for response in responses:
        final_response += response.text

    print(f"Response from Model: {final_response}")

    res = {
        "fulfillment_response": {"messages": [{"text": {"text": [final_response]}}]},
        "sessionInfo": {
            "parameters": {
                "account_status": account_status,
            }
        },
    }

    return res
