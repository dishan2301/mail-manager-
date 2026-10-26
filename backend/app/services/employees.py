COMPANY_EMAIL_DOMAIN = "indianinfotech.org"


def is_company_employee_email(address: str) -> bool:
    address=address.strip().casefold()
    return address.count("@")==1 and bool(address.split("@",1)[0]) and address.endswith("@"+COMPANY_EMAIL_DOMAIN) and not any(char.isspace() for char in address)
