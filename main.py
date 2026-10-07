import os
companies = ["JPM", "BAC", "C", "CAT", "DE", "HON"]
forms = ["10-K", "10-Q", "10-Q"]
for company in companies: 
    os.makedirs("data/raw/" + company, exist_ok=True)
    for form in forms:
        print(company, form)
print("Done")