# -*- coding: utf-8 -*-
"""Module compliance_suite.single_test_executor.py

This module contains class definition for generalized model of testing an api
route. The SingleTestExecutor executes a request, checks status code of the
response, validates the schema of the returned JSON object against the
corresponding schema, and sets the test result to 1 (success) or -1 (fail)

Todo:
    * handle query parameters
    * handle tests for not OK (!=200) response codes
"""

import requests

from compliance_suite.schema_validator import SchemaValidator
from compliance_suite.config.constants import *
import compliance_suite.exceptions.test_status_exception as tse

class SingleTestExecutor(object):
    """Executes API request, validates response and sets result to pass/fail

    The SingleTestExecutor is a generalized model for executing tests against
    the API. It executes a request, checks for response code, and validates
    the returned object against a schema.

    Attributes:
        uri (str): uri to be requested
        schema_file (str): JSON schema file to validate response against
        http_method (int): GET or POST request
        params (dict): parameters/filters to submit with query
        test (Test): reference to Test object
        runner (TestRunner): reference to TestRunner object
        media_types (list): all accepted media types
        headers (dict): key, value mapping of request header
        full_message (list): lists associated information with the api test,
            to be assigned to Test object and displayed in report under case
    """

    def __init__(self, uri, test, runner):
        """instantiates a SingleTestExecutor object
        
        Args:
            uri (str): uri to be requested
            test (Test): reference to Test object
            runner (TestRunner): reference to TestRunner object
        """

        self.uri = uri
        self.test = test
        self.runner = runner
        self.http_method = self.test.kwargs["http_method"]
        self.full_message = []
        self.__set_test_properties()
    
    def execute_test(self):
        """Test API URI, validate response and set test to pass/fail"""
        
        # set request headers
        for header_name, header_value in self.runner.headers.items():
            self.headers[header_name] = header_value

        # make GET/POST request
        apply_params = self.test.kwargs["apply_params"]
        request_method = REQUEST_METHOD[self.http_method]

        if apply_params == "no":
            response = request_method(self.uri, headers=self.headers)
            self.set_test_status(self.uri, {}, response)
        elif apply_params == "all":
            response = request_method(self.uri, headers=self.headers, 
                                      params=self.params)
            self.set_test_status(self.uri, self.params, response)
        elif apply_params == "some":
            some_params = {p: self.params[p] for p in 
                           self.test.kwargs["specified_params"]}
            response = request_method(self.uri, headers=self.headers, 
                                      params=some_params)
            self.set_test_status(self.uri, some_params, response)
        elif apply_params == "cases":
            constant_params = {}
            if 'specified_params' in set(self.test.kwargs.keys()):
                constant_params = {p: self.params[p] for p in
                                   self.test.kwargs["specified_params"]}
            case_params_keys = list(set(self.params.keys()).difference(
                set(constant_params.keys())))

            for key in list(case_params_keys):
                param_case = {key: self.params[key]}
                param_case.update(constant_params)
                response = request_method(self.uri, headers=self.headers, 
                                      params=param_case)
                self.set_test_status(self.uri, param_case, response)
    
    def set_test_status(self, uri, params, response):
        """Sets test status and messages based on response
        
        After making the API request, this method parses the response object
        and cross-references with the expected output (JSON schema, status code,
        etc). Test results are marked pass/fail/skip, and associated messages
        are added. The 3 steps of validating a single test case are as follows:
        1) validate content type/media type, 2) validate response status code,
        3) validate response body matches correct JSON schema

        Args:
            uri (str): requested uri
            params (dict): key-value mapping of supplied parameters
            response (Response): response object from the request
        """

        if self.test.result != -1:
            self.full_message.append(["Request", uri])
            self.full_message.append(["Params", str(params)])
            # only add response body if JSON format is expected
            if self.is_json:
                self.full_message.append(["Response Body", response.text])

            try:
                # Validation 1, Content-Type, Media Type validation
                # check response content type is in accepted media types
                response_media_type = self.__get_response_media_type(response)
                if not response_media_type in set(self.media_types):
                    raise tse.MediaTypeException(
                        "Response Content-Type '%s'" % response_media_type
                        + " not in request accepted media types: "
                        + str(self.media_types) 
                    )
                
                # Validation 2, Status Code match validation
                # if response code matches expected, validate against JSON
                # schema
                if response.status_code not in self.exp_status:
                    raise tse.StatusCodeException(
                        "Response status code: %s" % str(response.status_code)
                        + " not in expected status code(s): "
                        + str(sorted(list(self.exp_status)))
                    )

                # Validation 3, JSON Schema Validation
                # if JSON schema matches response body, test succeeds
                # if a JSON object can't be parsed from the response body,
                # then catch this error and assign exception

                # if JSON object/dict cannot be parsed from the response body,
                # raise a TestStatusException

                # if endpoint not expected to return JSON (is_json == False),
                # skip this step
                if self.is_json:
                    response_json = None
                    try:
                        response_json = response.json()
                    except ValueError as e:
                        raise tse.JsonParseException(str(e))

                    sv = SchemaValidator(self.schema_file)
                    validation_result = sv.validate_instance(response_json)
                    self.test.result = validation_result["status"]

                    if validation_result["status"] == -1:
                        raise tse.SchemaValidationException(
                            validation_result["message"])
                else:
                    self.test.result = 1

            except tse.TestStatusException as e:
                self.test.result = -1
                self.full_message.append(["Exception", 
                    str(e.__class__.__name__)])
                self.full_message.append(["Exception Message", str(e)])
                    
            finally:
                self.test.full_message = self.full_message

    def __get_response_media_type(self, response):
        """Get media type from 'Content-Type' field of response header"""

        ct = response.headers["Content-Type"].split(";")[0]
        return ct
    
    def __set_test_properties(self):
        self.__set_expected_status_code()
        self.__set_media_types()
        self.__set_params()
        self.__set_schema()

    def __set_expected_status_code(self):
        
        k = "expected_status"
        self.exp_status = \
            set([200]) if k not in self.test.kwargs.keys() \
                       else set(self.test.kwargs[k])
    
    def __set_media_types(self):
        """sets accepted media types and accept header from passed params"""

        self.media_types = []
        # assign accepted media types
        # check if default media types will be used for this test,
        # then add any other test-specific media types
        self.media_types = []
        use_default = \
            True if "use_default_media_types" not in self.test.kwargs.keys() \
            else self.test.kwargs["use_default_media_types"]
        if use_default:
            self.media_types = [a for a in DEFAULT_MEDIA_TYPES]
        add_test_specific = \
            False if "media_types" not in self.test.kwargs.keys() else True
        if add_test_specific:
            self.media_types += \
                [a for a in self.test.kwargs["media_types"]]
        self.headers = {"Accept": ", ".join(self.media_types) + ";"}

    def __set_params(self):
        params = self.test.kwargs["obj_instance"]["filters"]
        self.params = {k: params[k] for k in params.keys()}

        # check if request params need to be changed for this test type
        # if so, replace params with the replace value
        replace_params = False
        replace_value = None
        if "replace_params" in self.test.kwargs.keys():
            replace_params = self.test.kwargs["replace_params"]
        if replace_params:
            if "param_replacement" in self.test.kwargs.keys():
                for param_key in self.params.keys():
                    self.params[param_key] = \
                        self.test.kwargs["param_replacement"]
            elif "param_func" in self.test.kwargs.keys():
                self.test.kwargs["param_func"](self.params)
    
    def __set_schema(self):
        self.schema_file = None
        self.is_json = True

        if "schema_file" in self.test.kwargs.keys():
            self.schema_file = self.test.kwargs["schema_file"]
        else:
            self.schema_file = self.test.kwargs["schema_func"](self.params)
        
        if "is_json" in self.test.kwargs.keys():
            self.is_json = self.test.kwargs["is_json"]
