Respa-Exchange
==============


A connector for bidirectional synchronization of [Respa][respa]
event information with Microsoft Exchange resource calendars.

Installation
------------

Respa-Exchange is a Django app that hooks to Respa using Django signals.

* Add `respa_exchange` to your `INSTALLED_APPS`.
* Run Django `migrate` and restart your app server, etc.
* You should now see Respa-Exchange entries in the Django admin.

Development/howto
-----------------

You'll need a copy of [Respa][respa] to develop Respa-Exchange against.

* Set up a virtualenv.
* Install Respa's requirements: `pip install -r requirements.txt`
* Run `py.test`. Everything should work.

Requirements
------------

* Microsoft Exchange, either on-premises installation with
  Exchange Web Services enabled or a Office 365 account in the cloud

Notes about the implementation
------------------------------
### Authentication ###
Respa-Exchange authenticates itself to Exchange's EWS API by Basic Auth. The production installation of Tampere Respa uses the Office 365 cloud, and Microsoft plans to disable Basic Auth in the cloud during 2021. OAuth2.0 has been attempted as a replacement authentication method, but so far a configuration that would use OAuth and also be compatible with all security policies in place has not been found. In particular, the OAuth configurations attempted in the past require too wide permissions for Respa, read and write access to all mailboxes in the tenant. Documentation about different possible OAuth configurations is available here: https://docs.microsoft.com/en-us/exchange/client-developer/exchange-web-services/how-to-authenticate-an-ews-application-by-using-oauth. The Office 365 might have other APIs available that can do the same things as the currently used EWS does, migrating Respa-Exchange to a different API might be necessary.

Acknowledgements
----------------

* [LinkedIn's PyExchange][pyex] project was a tremendous help. Thanks!

---

[respa]: https://github.com/City-of-Helsinki/respa
[pyex]: https://github.com/linkedin/pyexchange
