from common import *

DEPLOYMENT_LEVEL = "staging"

DEBUG = False

ALLOWED_HOSTS = ["ias-ezid-stg.cdlib.org"]

injectPasswords(DEPLOYMENT_LEVEL)
