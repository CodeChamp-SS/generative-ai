from concurrent.futures import ThreadPoolExecutor
from os import environ
from typing import Dict

import functions_framework
from google.cloud import bigquery
import vertexai
from vertexai.generative_models import GenerativeModel
import vertexai.preview.generative_models as generative_models

project_id = environ.get("PROJECT_ID")
client: bigquery.Client = bigquery.Client()


def run(name: str, statement: str) -> tuple[str, bigquery.table.RowIterator]:
    return name, client.query(statement).result()  # blocks the thread


def run_all(statements: Dict[str, str]) -> Dict[str, bigquery.table.RowIterator]:
    with ThreadPoolExecutor() as executor:
        jobs = []
        for name, statement in statements.items():
            jobs.append(executor.submit(run, name, statement))
        result = dict([job.result() for job in jobs])
    return result


@functions_framework.http
def travel_card_recommendation(request):
    request_json = request.get_json(silent=True)

    client = bigquery.Client()

    customer_id = request_json["sessionInfo"]["parameters"]["cust_id"]

    if customer_id is not None:
        print("Customer ID ", customer_id)
    else:
        print("Customer ID not defined")

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
                                    "It seems you have entered an incorrect Customer ID. Please try again."
                                ]
                            }
                        }
                    ]
                }
            }
            return res

    query_age_on_book = f"""SELECT age_on_book as customer_age_on_book FROM `{project_id}.DummyBankDataset.Customer` where customer_id = {customer_id}"""
    result_age_on_book = client.query(query_age_on_book)
    customer_age_on_book = 0
    for row in result_age_on_book:
        customer_age_on_book = row["customer_age_on_book"]

    if customer_age_on_book < 365:
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
        model = GenerativeModel("gemini-1.0-pro-002")
        response = model.generate_content(
            """You are a chatbot for a bank application.
        Tell the user politely that they are not eligible for the the credit card as they are new customer. Only cutomer older than 1 year with the bank are eligible for credit card.
        Ask the user to wait and ask if they want anything else like mutual funds or fixed deposit.
        Write in a professional and business-neutral tone.
        Word Limit is 60 words.
        The message comes in middle of conversation so don't greet the user with Hello/Hi.
        The user lives in India.
        The message should be in a conversation-like manner based on the Account Status.
        The message should be in second person's perespective tone.
        """,
            generation_config=generation_config,
            safety_settings=safety_settings,
            stream=True,
        )

        final_response = ""
        for response in response:
            final_response += response.tex

        res = {
            "fulfillment_response": {
                "messages": [{"text": {"text": [final_response.text]}}]
            },
            "target_page": "projects/{project_id}/locations/asia-south1/agents/118233dd-f023-4dad-b302-3906a7365ccc/flows/00000000-0000-0000-0000-000000000000/pages/06e52d7c-536a-4cbf-baba-4fe7d686e472",
        }
        return res

    query_travel_expense = f"""
    SELECT SUM(transaction_amount) as travel_expense from `{project_id}.DummyBankDataset.AccountTransactions`
    WHERE debit_credit_indicator = 'Debit' and ac_id IN (SELECT account_id FROM `{project_id}.DummyBankDataset.Account` where customer_id = {customer_id}) and sub_category = 'Travel'
    """

    result_travel_expense = client.query(query_travel_expense)

    scheme_name = []
    one_month_return = []
    ttm_return = []

    asset_amount = 0
    debt_amount = 0
    total_income = 0
    total_expenditure = 0
    first_name = ""
    total_investment = 0
    total_high_risk_investment = 0
    amount_transfered = ""
    average_mothly_expense = 0
    last_month_expense = 0
    user_accounts = []
    travel_expense = 0
    credit_card = ""

    for row in result_travel_expense:
        if row["travel_expense"] is not None:
            travel_expense += int(row["travel_expense"])

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
        SELECT SUM(Number_of_Units * Latest_NAV) as total_mf_investment FROM `DummyBankDataset.MutualFundAccountHolding` where account_no in (
            select account_id from `DummyBankDataset.Account` where customer_id = {customer_id}
        );
    """

    query_high_risk_mf = f"""
        select SUM(Number_of_Units * Latest_NAV) as total_high_risk_investment from `DummyBankDataset.MutualFundAccountHolding` where risk_category > 4 and account_no in (
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

    query_average_mothly_expense = f"""SELECT AVG(total_amount) as average_mothly_expense from (
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
            "query_average_mothly_expense": query_average_mothly_expense,
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

    asset_amount = 0
    debt_amount = 0
    total_income = 0
    total_expenditure = 0
    first_name = ""
    total_investment = 0
    total_high_risk_investment = 0
    amount_transfered = ""
    account_status = ""
    average_mothly_expense = 0
    last_month_expense = 0
    user_accounts = []

    for row in res["query_average_mothly_expense"]:
        if row["average_mothly_expense"] is not None:
            average_mothly_expense = int(row["average_mothly_expense"])

    for row in res["query_last_month_expense"]:
        if row["last_month_expense"] is not None:
            last_month_expense = int(row["last_month_expense"])

    for row in res["query_assets"]:
        if row["asset"] is not None:
            asset_amount = int(row["asset"])

    for row in res["query_debts"]:
        if row["debt"] is not None:
            debt_amount = int(row["debt"])

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

    if account_status == "Healthy":
        credit_card = "Cymbal Luxury Lifestyle Card"
    elif account_status == "Needs Attention":
        credit_card = "Cymbal No-annual-fee Rewards Card"
    else:
        credit_card = "Cymbal Secured Credit Card"

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
    model = GenerativeModel("gemini-1.0-pro-002")
    response = model.generate_content(
    f"""
        You are a chatbot for a bank application you have been given the Credit Card as {credit_card}.
        You have to recommend the given credit card to the user and explain the benefits of the credit card.
        Write in a professional and business-neutral tone.
        Word Limit is 100 words.
        The message comes in middle of conversation so don't greet the user with Hello/Hi.
        The user lives in India.
        Assume the currency that you suggest to the user to be Indian Rupees(₹).
        ONLY USE INDIAN RUPEES(₹) EVERYWHERE.
        The amount should comma seprated in indian rupees format.
        The message should be in a conversation-like manner based on the Account Status.
        The message should only be based on the information presented above.
        The message should be in second person's perespective tone.
    """,
        generation_config=generation_config,
        safety_settings=safety_settings,
        stream=True,
    )

    final_response = ""
    for response in response:
        final_response += response.text

    res = {
        "fulfillment_response": {
            "messages": [
                {"text": {"text": [final_response.text]}},
                {"text": {"text": ["Would you like to apply for this card?"]}},
            ]
        },
        "sessionInfo": {
            "parameters": {
                "credit_card": credit_card,
            }
        },
    }

    return res
