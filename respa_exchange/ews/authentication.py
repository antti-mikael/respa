from django.conf import settings
from requests_oauthlib import OAuth2
from msal import PublicClientApplication


class Oauth2Authenticate:
    """
        Class used to authenticate by username and password using MSAL library
        and create Oauth2 object by using token received from authentication.
    """
    client_id = settings.RESPA_EXCHANGE_CLIENT_ID
    tenant_id = settings.RESPA_EXCHANGE_TENANT_ID

    def __init__(self, username, password, client_id, tenant_id):
        self.username = username
        self.password = password
        if self.client_id is None:
            self.client_id = client_id
        if self.tenant_id is None:
            self.tenant_id = tenant_id

    def authenticate(self):
        """
            Authenticate by username and password and in case of successful authentication
            create Oauth2 object by using the received token.
        """
        app = PublicClientApplication(
            client_id=self.client_id,
            authority="https://login.microsoftonline.com/" + self.tenant_id
        )

        response = app.acquire_token_by_username_password(
            username=self.username,
            password=self.password,
            scopes=["https://outlook.office365.com/EWS.AccessAsUser.All"]
        )

        if "access_token" in response:
            token_type = response['token_type']
            access_token = response['access_token']

            token = {
                'token_type': token_type,
                'access_token': access_token
            }
        else:
            raise Exception(f"Unsuccessful authentication for user {self.username}")

        oauth2 = OAuth2(client_id=self.client_id, token=token)

        return oauth2
