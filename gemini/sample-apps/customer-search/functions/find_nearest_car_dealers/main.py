from os import environ

import functions_framework
from google.cloud import bigquery
import requests
import vertexai
from vertexai.generative_models import GenerativeModel, Part, FinishReason
import vertexai.preview.generative_models as generative_models

project_id = environ.get("PROJECT_ID")
api_key = environ.get("API_KEY")


@functions_framework.http
def hello_http(request):
    headers = {"Content-Type": "application/json"}

    request_json = request.get_json(silent=True)

    client = bigquery.Client()

    customer_id = request_json["sessionInfo"]["parameters"]["cust_id"]

    if customer_id is not None:
        print("Customer ID ", customer_id)
    else:
        print("Customer ID not defined")

    query_assets = f"""
        SELECT sum(avg_monthly_bal) as asset FROM `{project_id}.DummyBankDataset.Account`
        where customer_id = {customer_id} and product in ('Savings A/C ', 'Savings Salary A/C ', 'Premium Current A/C ', 'Fixed Deposit', 'Flexi Deposit');
    """

    result_asset = client.query(query_assets)
    asset_amount = 0
    for row in result_asset:
        if row["asset"] is not None:
            asset_amount = int(row["asset"])

    category = ""
    if asset_amount < 10000000:
        category = "Standard"
    else:
        category = "Premium"

    query_car_dealers = (
        "SELECT brand, dealer_name, address FROM"
        f" `{project_id}.DummyBankDataset.CarDealers` where category ="
        f" '{category}'"
    )

    query_cust_address = f"""
        SELECT Address_2nd_Line, Address_3rd_Line, city, state, Plus_Code FROM `{project_id}.DummyBankDataset.Customer` where customer_id = {customer_id}
    """

    result_car_dealers = client.query(query_car_dealers)

    result_cust_address = client.query(query_cust_address)

    car_dealers = {}
    for row in result_car_dealers:
        if row["brand"] not in car_dealers:
            car_dealers[row["brand"]] = []
        car_dealers[row["brand"]].append((row["dealer_name"], row["address"]))

    cust_address = ""
    for row in result_cust_address:
        cust_address = (
            row["Address_2nd_Line"]
            + ", "
            + row["Address_3rd_Line"]
            + ", "
            + row["city"]
            + ", "
            + row["state"]
            + " "
            + str(row["Plus_Code"])
        )

    distances = []
    for brand in car_dealers:
        for dealer_name, dealer_address in car_dealers[brand]:
            dist_api_url = (
                f"https://maps.googleapis.com/maps/api/distancematrix/json?destinations={dealer_name},"
                f" {dealer_address}&origins={cust_address}&key={api_key}"
            )
            dist_res = requests.get(dist_api_url, headers=headers)
            dist_res_json = dist_res.json()
            distances.append(
                (
                    dist_res_json["rows"][0]["elements"][0]["distance"]["value"],
                    (dealer_name, dealer_address),
                )
            )

    distances.sort()

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
    
    responses = model.generate_content(
        f"""You are a chatbot for Cymbal bank. The user is interested in buying a new car. Acknowledge that the user is not interested in Fixed Deposit because they are saving to purchase a new car and provide them information about some partner car dealers near his location using the following:
    Distances = {distances}

    Provide the user information about closest 5 car dealers along with address of their showrooms from Distances with proper spacing and indentation for clear readability. Also provide some interesting offers for bank's customers for each of the dealers in a professional and conversation-like manner.
    The currency to be used is Indian Rupee,i.e.,₹.

    Write in a professional and business-neutral tone.
    Do not greet the user.
    The summary should be in a conversation-like manner.
    The summary should only be based on the information presented above.
    The summary should be in pointers.
    The summary for is for the user to read. So summary should be in second person's perespective tone.
    """,
        generation_config=generation_config,
        safety_settings=safety_settings,
        stream=True,
    )

    final_response = ""
    for response in responses:
        final_response += response.text 
        
    res = {
        "fulfillment_response": {"messages": [{"text": {"text": [final_response]}}]},
        "sessionInfo": {
            "parameters": {"vehicle_type": "Car", "showrooms": final_response}
        },
    }
    return res
