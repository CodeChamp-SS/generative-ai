from os import environ

import functions_framework
from google.cloud import bigquery

project_id = environ.get("PROJECT_ID")


@functions_framework.http
def hello_http(request):
    request_json = request.get_json(silent=True)

    client = bigquery.Client()

    print(request_json["sessionInfo"]["parameters"])

    customer_id = request_json["sessionInfo"]["parameters"]["cust_id"]
    # customer_id = 235813
    # 342345, 592783

    if customer_id is not None:
        print("Customer ID ", customer_id)
    else:
        print("Customer ID not defined")

    query_check_cust_id = f"""
        SELECT EXISTS(SELECT * FROM `{project_id}.DummyBankDataset.Account` where customer_id = {customer_id}) as check
    """

    result_query_check_cust_id = client.query(query_check_cust_id)
    for row in result_query_check_cust_id:
        print(row["check"])
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
            print(res)
            return res

    res = {
        "fulfillment_response": {
            "messages": [
                {"text": {"text": ["That's great! What can I help you with today?"]}}
            ]
        }
    }
    print(res)
    return res
