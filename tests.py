import unittest

from botocore.exceptions import ParamValidationError
from botocore.stub import Stubber
from mock import patch
from envs import env
from moto import mock_cognitoidp
import boto3

import pycognito
from pycognito import Cognito, UserObj, GroupObj, TokenVerificationException
from pycognito.aws_srp import AWSSRP


def _mock_authenticate_user(_, client=None):
    return {
        "AuthenticationResult": {
            "TokenType": "admin",
            "IdToken": "dummy_token",
            "AccessToken": "dummy_token",
            "RefreshToken": "dummy_token",
        }
    }


def _mock_get_params(_):
    return {"USERNAME": "bob", "SRP_A": "srp"}


def _mock_verify_tokens(self, token, id_name, token_use):
    if "wrong" in token:
        raise TokenVerificationException
    setattr(self, id_name, token)


class UserObjTestCase(unittest.TestCase):
    def setUp(self):
        if env("USE_CLIENT_SECRET", "False") == "True":
            self.app_id = env("COGNITO_APP_WITH_SECRET_ID")
        else:
            self.app_id = env("COGNITO_APP_ID")
        self.cognito_user_pool_id = env("COGNITO_USER_POOL_ID", "us-east-1_123456789")
        self.username = env("COGNITO_TEST_USERNAME")

        self.user = Cognito(
            user_pool_id=self.cognito_user_pool_id,
            client_id=self.app_id,
            username=self.username,
        )

        self.user_metadata = {
            "user_status": "CONFIRMED",
            "username": "bjones",
        }
        self.user_info = [
            {"Name": "name", "Value": "Brian Jones"},
            {"Name": "given_name", "Value": "Brian"},
            {"Name": "birthdate", "Value": "12/7/1980"},
        ]

    def test_init(self):
        user = UserObj("bjones", self.user_info, self.user, self.user_metadata)
        self.assertEqual(user.username, self.user_metadata.get("username"))
        self.assertEqual(user.name, self.user_info[0].get("Value"))
        self.assertEqual(user.user_status, self.user_metadata.get("user_status"))


class GroupObjTestCase(unittest.TestCase):
    def setUp(self):
        if env("USE_CLIENT_SECRET", "False") == "True":
            self.app_id = env("COGNITO_APP_WITH_SECRET_ID")
        else:
            self.app_id = env("COGNITO_APP_ID")
        self.cognito_user_pool_id = env("COGNITO_USER_POOL_ID", "us-east-1_123456789")
        self.group_data = {"GroupName": "test_group", "Precedence": 1}
        self.cognito_obj = Cognito(
            user_pool_id=self.cognito_user_pool_id, client_id=self.app_id
        )

    def test_init(self):
        group = GroupObj(group_data=self.group_data, cognito_obj=self.cognito_obj)
        self.assertEqual(group.group_name, "test_group")
        self.assertEqual(group.precedence, 1)


class CognitoAuthTestCase(unittest.TestCase):
    def setUp(self):
        if env("USE_CLIENT_SECRET") == "True":
            self.app_id = env("COGNITO_APP_WITH_SECRET_ID", "app")
            self.client_secret = env("COGNITO_CLIENT_SECRET")
        else:
            self.app_id = env("COGNITO_APP_ID", "app")
            self.client_secret = None
        self.cognito_user_pool_id = env("COGNITO_USER_POOL_ID", "us-east-1_123456789")
        self.username = env("COGNITO_TEST_USERNAME", "bob")
        self.password = env("COGNITO_TEST_PASSWORD", "bobpassword")
        self.user = Cognito(
            self.cognito_user_pool_id,
            self.app_id,
            username=self.username,
            client_secret=self.client_secret,
        )

    @patch("pycognito.aws_srp.AWSSRP.authenticate_user", _mock_authenticate_user)
    @patch("pycognito.Cognito.verify_token", _mock_verify_tokens)
    def test_authenticate(self):

        self.user.authenticate(self.password)
        self.assertNotEqual(self.user.access_token, None)
        self.assertNotEqual(self.user.id_token, None)
        self.assertNotEqual(self.user.refresh_token, None)

    @patch("pycognito.aws_srp.AWSSRP.authenticate_user", _mock_authenticate_user)
    @patch("pycognito.Cognito.verify_token", _mock_verify_tokens)
    def test_verify_token(self):
        self.user.authenticate(self.password)
        bad_access_token = "{}wrong".format(self.user.access_token)

        with self.assertRaises(TokenVerificationException):
            self.user.verify_token(bad_access_token, "access_token", "access")

    @patch("pycognito.Cognito", autospec=True)
    def test_register(self, cognito_user):
        user = cognito_user(
            self.cognito_user_pool_id, self.app_id, username=self.username
        )
        base_attr = dict(
            given_name="Brian",
            family_name="Jones",
            name="Brian Jones",
            email="bjones39@capless.io",
            phone_number="+19194894555",
            gender="Male",
            preferred_username="billyocean",
        )

        user.set_base_attributes(**base_attr)
        user.register("sampleuser", "sample4#Password")

    @patch("pycognito.aws_srp.AWSSRP.authenticate_user", _mock_authenticate_user)
    @patch("pycognito.Cognito.verify_token", _mock_verify_tokens)
    @patch("pycognito.Cognito._add_secret_hash", return_value=None)
    def test_renew_tokens(self, _):

        stub = Stubber(self.user.client)

        # By the stubber nature, we need to add the sequence
        # of calls for the AWS SRP auth to test the whole process
        stub.add_response(
            method="initiate_auth",
            service_response={
                "AuthenticationResult": {
                    "TokenType": "admin",
                    "IdToken": "dummy_token",
                    "AccessToken": "dummy_token",
                    "RefreshToken": "dummy_token",
                },
                "ResponseMetadata": {"HTTPStatusCode": 200},
            },
            expected_params={
                "ClientId": self.app_id,
                "AuthFlow": "REFRESH_TOKEN_AUTH",
                "AuthParameters": {"REFRESH_TOKEN": "dummy_token"},
            },
        )

        with stub:
            self.user.authenticate(self.password)
            self.user.renew_access_token()
            stub.assert_no_pending_responses()

    @patch("pycognito.Cognito", autospec=True)
    def test_update_profile(self, cognito_user):
        user = cognito_user(
            self.cognito_user_pool_id, self.app_id, username=self.username
        )
        user.authenticate(self.password)
        user.update_profile({"given_name": "Jenkins"})

    def test_admin_get_user(self):
        stub = Stubber(self.user.client)

        stub.add_response(
            method="admin_get_user",
            service_response={
                "Enabled": True,
                "UserStatus": "CONFIRMED",
                "Username": self.username,
                "UserAttributes": [],
            },
            expected_params={
                "UserPoolId": self.cognito_user_pool_id,
                "Username": self.username,
            },
        )

        with stub:
            u = self.user.admin_get_user(self.username)
            self.assertEqual(u.username, self.username)
            stub.assert_no_pending_responses()

    def test_check_token(self):
        # This is a sample JWT with an expiration time set to January, 1st, 3000
        self.user.access_token = (
            "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG"
            "9lIiwiaWF0IjoxNTE2MjM5MDIyLCJleHAiOjMyNTAzNjgwMDAwfQ.C-1gPxrhUsiWeCvMvaZuuQYarkDNAc"
            "pEGJPIqu_SrKQ"
        )
        self.assertFalse(self.user.check_token())

    @patch("pycognito.Cognito", autospec=True)
    def test_validate_verification(self, cognito_user):
        u = cognito_user(self.cognito_user_pool_id, self.app_id, username=self.username)
        u.validate_verification("4321")

    @patch("pycognito.Cognito", autospec=True)
    def test_confirm_forgot_password(self, cognito_user):
        u = cognito_user(self.cognito_user_pool_id, self.app_id, username=self.username)
        u.confirm_forgot_password("4553", "samplepassword")
        with self.assertRaises(TypeError):
            u.confirm_forgot_password(self.password)

    @patch("pycognito.aws_srp.AWSSRP.authenticate_user", _mock_authenticate_user)
    @patch("pycognito.Cognito.verify_token", _mock_verify_tokens)
    @patch("pycognito.Cognito.check_token", return_value=True)
    def test_change_password(self, _):
        # u = cognito_user(self.cognito_user_pool_id, self.app_id,
        #                  username=self.username)
        self.user.authenticate(self.password)

        stub = Stubber(self.user.client)

        stub.add_response(
            method="change_password",
            service_response={"ResponseMetadata": {"HTTPStatusCode": 200}},
            expected_params={
                "PreviousPassword": self.password,
                "ProposedPassword": "crazypassword$45DOG",
                "AccessToken": self.user.access_token,
            },
        )

        with stub:
            self.user.change_password(self.password, "crazypassword$45DOG")
            stub.assert_no_pending_responses()

        with self.assertRaises(ParamValidationError):
            self.user.change_password(self.password, None)

    def test_set_attributes(self):
        user = Cognito(self.cognito_user_pool_id, self.app_id)
        user._set_attributes(
            {"ResponseMetadata": {"HTTPStatusCode": 200}}, {"somerandom": "attribute"}
        )
        self.assertEqual(user.somerandom, "attribute")

    @patch("pycognito.Cognito.verify_token", _mock_verify_tokens)
    def test_admin_authenticate(self):

        stub = Stubber(self.user.client)

        # By the stubber nature, we need to add the sequence
        # of calls for the AWS SRP auth to test the whole process
        stub.add_response(
            method="admin_initiate_auth",
            service_response={
                "AuthenticationResult": {
                    "TokenType": "admin",
                    "IdToken": "dummy_token",
                    "AccessToken": "dummy_token",
                    "RefreshToken": "dummy_token",
                }
            },
            expected_params={
                "UserPoolId": self.cognito_user_pool_id,
                "ClientId": self.app_id,
                "AuthFlow": "ADMIN_NO_SRP_AUTH",
                "AuthParameters": {
                    "USERNAME": self.username,
                    "PASSWORD": self.password,
                },
            },
        )

        with stub:
            self.user.admin_authenticate(self.password)
            self.assertNotEqual(self.user.access_token, None)
            self.assertNotEqual(self.user.id_token, None)
            self.assertNotEqual(self.user.refresh_token, None)
            stub.assert_no_pending_responses()


class AWSSRPTestCase(unittest.TestCase):
    def setUp(self):
        if env("USE_CLIENT_SECRET") == "True":
            self.client_secret = env("COGNITO_CLIENT_SECRET")
            self.app_id = env("COGNITO_APP_WITH_SECRET_ID", "app")
        else:
            self.app_id = env("COGNITO_APP_ID", "app")
            self.client_secret = None
        self.cognito_user_pool_id = env("COGNITO_USER_POOL_ID", "us-east-1_123456789")
        self.username = env("COGNITO_TEST_USERNAME")
        self.password = env("COGNITO_TEST_PASSWORD")
        self.aws = AWSSRP(
            username=self.username,
            password=self.password,
            pool_region="us-east-1",
            pool_id=self.cognito_user_pool_id,
            client_id=self.app_id,
            client_secret=self.client_secret,
        )

    def tearDown(self):
        del self.aws

    @patch("pycognito.aws_srp.AWSSRP.get_auth_params", _mock_get_params)
    @patch("pycognito.aws_srp.AWSSRP.process_challenge", return_value={})
    def test_authenticate_user(self, _):

        stub = Stubber(self.aws.client)

        # By the stubber nature, we need to add the sequence
        # of calls for the AWS SRP auth to test the whole process
        stub.add_response(
            method="initiate_auth",
            service_response={
                "ChallengeName": "PASSWORD_VERIFIER",
                "ChallengeParameters": {},
            },
            expected_params={
                "AuthFlow": "USER_SRP_AUTH",
                "AuthParameters": _mock_get_params(None),
                "ClientId": self.app_id,
            },
        )

        stub.add_response(
            method="respond_to_auth_challenge",
            service_response={
                "AuthenticationResult": {
                    "IdToken": "dummy_token",
                    "AccessToken": "dummy_token",
                    "RefreshToken": "dummy_token",
                }
            },
            expected_params={
                "ClientId": self.app_id,
                "ChallengeName": "PASSWORD_VERIFIER",
                "ChallengeResponses": {},
            },
        )

        with stub:
            tokens = self.aws.authenticate_user()
            self.assertTrue("IdToken" in tokens["AuthenticationResult"])
            self.assertTrue("AccessToken" in tokens["AuthenticationResult"])
            self.assertTrue("RefreshToken" in tokens["AuthenticationResult"])
            stub.assert_no_pending_responses()



class CognitoAdminTestCase(unittest.TestCase):

    def setUp(self):
        self.cognito_idp_patcher = mock_cognitoidp()
        self.mock_cognitoidp = self.cognito_idp_patcher.start()
        self.mock_conn = boto3.client("cognito-idp", "us-west-2")
        self.pool_id = self.mock_conn.create_user_pool(PoolName="userpool")["UserPool"]["Id"]
        self.mock_conn.admin_create_user(UserPoolId=self.pool_id, Username="default_user", UserAttributes=[{"Name":"thing", "Value": "Default User"}])
        self.mock_conn.create_group(GroupName="default_group", UserPoolId=self.pool_id)
        self.mock_conn.create_group(GroupName="test_group", UserPoolId=self.pool_id)
        self.mock_conn.admin_add_user_to_group(UserPoolId=self.pool_id, Username="default_user", GroupName="default_group")
        self.client_id = 'clientid'
        self.client_secret = 'clientsecret'

        self.access_key_id = 'accesskeyid'
        self.secret_access_key = 'secretaccesskey'
        self.cognito = pycognito.Cognito(self.pool_id,
                                         self.client_id,
                                         client_secret=self.client_secret,
                                         access_key=self.access_key_id,
                                         secret_key=self.secret_access_key)

    def tearDown(self):
        self.cognito_idp_patcher.stop()

    def test_admin_create_user_explicit_password(self):
        ret = self.cognito.admin_create_user("test_user", "password")
        self.assertIsInstance(ret, UserObj)

    def test_admin_create_user_no_password(self):
        ret = self.cognito.admin_create_user("test_user")
        self.assertIsInstance(ret, UserObj)

    def test_admin_create_user_with_attributes(self):
        ret = self.cognito.admin_create_user("test_user", thing="Test User")
        self.assertEqual(ret.thing, "Test User")

    def test_admin_resend_invitation(self):
        ret = self.cognito.admin_resend_invitation("default_user")
        self.assertIsInstance(ret, UserObj)

    def test_admin_resend_invitation_preserves_groups_if_omitted(self):
        ret = self.cognito.admin_resend_invitation("default_user")
        groups = self.cognito.admin_list_groups_for_user("default_user")
        self.assertEqual(groups, ["default_group"])

    def test_admin_resend_invitation_overwrites_groups_if_passed(self):
        ret = self.cognito.admin_resend_invitation("default_user", groups=[])
        groups = self.cognito.admin_list_groups_for_user("default_user")
        self.assertEqual(groups, [])

    def test_admin_resend_invitation_missing_user(self):
        with self.assertRaises(self.mock_conn.exceptions.UserNotFoundException):
            ret = self.cognito.admin_resend_invitation("test_user")

    def test_admin_delete_user(self):
        self.cognito.admin_delete_user("default_user")

    def test_admin_get_user(self):
        ret = self.cognito.admin_get_user("default_user")
        self.assertEqual(ret.thing, "Default User")

    def test_admin_reset_password(self):
        try:
            ret = self.cognito.admin_reset_password("default_user")
        except NotImplementedError:
            unittest.skip("admin_reset_password not yet supported by moto")

    def test_admin_list_groups_for_user(self):
        ret = self.cognito.admin_list_groups_for_user("default_user")
        self.assertEqual(ret, ["default_group"])

    def test_admin_add_user_to_group(self):
        self.cognito.admin_add_user_to_group("default_user", "test_group")
        groups = self.cognito.admin_list_groups_for_user("default_user")
        self.assertIn("test_group", groups)

    def test_admin_remove_user_from_group(self):
        self.cognito.admin_remove_user_from_group("default_user", "default_group")
        groups = self.cognito.admin_list_groups_for_user("default_user")
        self.assertNotIn("default_group", groups)

    def test_admin_enable_user(self):
        ret = self.cognito.admin_enable_user("default_user")
        user = self.cognito.admin_get_user("default_user")
        self.assertTrue(user.enabled)

    def test_admin_disable_user(self):
        ret = self.cognito.admin_disable_user("default_user")
        user = self.cognito.admin_get_user("default_user")
        self.assertFalse(user.enabled)

    def test_admin_set_password(self):
        self.cognito.admin_set_user_password(username="default_user", password="newpassword")

    def test_admin_user_global_sign_out(self):
        try:
            self.cognito.admin_user_global_sign_out("default_user")
        except NotImplementedError:
            unittest.skip("admin_user_global_sign_out not yet supported by moto")

if __name__ == "__main__":
    unittest.main()
