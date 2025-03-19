# -*- coding: utf-8 -*-
# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.

import logging

from uuid import uuid4
from lxml import etree, html

from odoo import api, _
from odoo.exceptions import UserError
from odoo.addons.payment_authorize.models.authorize_request import AuthorizeAPI
from odoo.addons.payment import utils as payment_utils

_logger = logging.getLogger(__name__)


def _partner_split_name(partner_name):
    if partner_name: return " ".join(partner_name.split()[:-1]), partner_name.split()[-1]
    return ('', '')

def _prepare_authorization_transaction_request(self, transaction_type, tx_data, tx):
    # The billTo parameter is required for new ACH transactions (transactions without a payment.token),
    # but is not allowed for transactions with a payment.token.
    bill_to, ship_to = {}, {}
    authorize_partner_id = False
    if 'profile' not in tx_data:
        if tx_data.get('authorize_partner_id', False):
            authorize_partner_id = tx_data.get('authorize_partner_id', False)
            del tx_data['authorize_partner_id']
        partner_name = ''
        if tx.partner_id and tx.partner_id.name:
            partner_name = tx.partner_id.name
        elif tx.partner_id.parent_id and tx.partner_id.parent_id.name:
            partner_name = tx.partner_id.parent_id.name
        split_name = _partner_split_name(partner_name)
        bill_to = {
            'billTo': {
                'firstName': '' if tx.partner_id.is_company else (split_name and split_name[0][:50] or ''),
                'lastName': split_name[1][:50] or '',  # lastName is always required
                'company': tx.partner_name[:50] if tx.partner_id.is_company and tx.partner_name else '',
                'address': tx.partner_address or '',
                'city': tx.partner_city or '',
                'state': tx.partner_state_id.name or '',
                'zip': tx.partner_zip or '',
                'country': tx.partner_country_id.name or '',
            },
        }
        if tx.sale_order_ids and tx.sale_order_ids[0].partner_shipping_id:
            partner_id = tx.sale_order_ids[0].partner_shipping_id
        else:
            partner_id = tx.partner_id

        partner_name = ''
        if partner_id and partner_id.name:
            partner_name = partner_id.name
        elif partner_id.parent_id and partner_id.parent_id.name:
            partner_name = partner_id.parent_id.name

        shipping_split_name = _partner_split_name(partner_name)
        ship_to = {
            'shipTo': {
                'firstName': '' if tx.partner_id.is_company else (shipping_split_name and shipping_split_name[0][:50] or ''),
                'lastName': shipping_split_name and shipping_split_name[1][:50] or '',  # lastName is always required
                'company': partner_id and partner_id.parent_id and partner_id.parent_id.name[:50] or \
                            partner_id and partner_id.name[:50] or '',
                'address': partner_id.street or '',
                'city': partner_id.city or '',
                'state': partner_id.state_id.name or '',
                'zip': partner_id.zip or '',
                'country': partner_id.country_id.name or '',
            },
        }
    # These keys have to be in the order defined in
    # https://apitest.authorize.net/xml/v1/schema/AnetApiSchema.xsd
    res = {
        'transactionRequest': {
            'transactionType': transaction_type,
            'amount': str(tx.amount),
            **tx_data,
            'order': {
                'invoiceNumber': tx.reference[:20],
                'description': tx.reference[:255],
            },
            'customer': {
                'email': tx.partner_email or '',
            },
            **bill_to,
            **ship_to,
            'customerIP': payment_utils.get_customer_ip_address(),
        }
    }
    # if res.get('transactionRequest').get('customer') and authorize_partner_id and authorize_partner_id.merchant_id:
    #     res.get('transactionRequest').get('customer').update({
    #         'type': 'individual',
    #         'id': authorize_partner_id and authorize_partner_id.merchant_id or '',
    #     })
    return res

def authorize(self, tx, token=None, opaque_data=None):
    tx_data = self._prepare_tx_data(token=token, opaque_data=opaque_data)
    authorize_partner_id, authorizeAPI, provider_id = tx._get_partner_authorize_profile()
    if tx.tokenize and not token and tx.partner_id.authorize_partner_ids and authorize_partner_id:
        payment_profile = AuthorizeAPI.create_customer_payment_profile(self, partner=tx.partner_id, customer_profile_id=authorize_partner_id.customer_profile_id, tx=tx, opaque_data=opaque_data)
        tx_data = {
            'profile': {
                'customerProfileId': payment_profile.get('customerProfileId', False),
                'paymentProfile': {
                    'paymentProfileId': payment_profile.get('customerPaymentProfileId', False),
                }
            }
        }
    elif tx.partner_id.authorize_partner_ids and authorize_partner_id and opaque_data:
        tx_data.update({'authorize_partner_id': authorize_partner_id})

    response = self._make_request(
        'createTransactionRequest',
        self._prepare_authorization_transaction_request('authOnlyTransaction', tx_data, tx)
    )
    return self._format_response(response, 'auth_only')

def auth_and_capture(self, tx, token=None, opaque_data=None):
    tx_data = self._prepare_tx_data(token=token, opaque_data=opaque_data)
    authorize_partner_id, authorizeAPI, provider_id = tx._get_partner_authorize_profile()

    if tx.tokenize and not token and tx.partner_id.authorize_partner_ids and authorize_partner_id:
        payment_profile = AuthorizeAPI.create_customer_payment_profile(self, partner=tx.partner_id, customer_profile_id=authorize_partner_id.customer_profile_id, tx=tx, opaque_data=opaque_data)
        tx_data = {
            'profile': {
                'customerProfileId': payment_profile.get('customerProfileId', False),
                'paymentProfile': {
                    'paymentProfileId': payment_profile.get('customerPaymentProfileId', False),
                }
            }
        }
    elif tx.partner_id.authorize_partner_ids and authorize_partner_id and opaque_data:
        tx_data.update({'authorize_partner_id': authorize_partner_id})

    response = self._make_request(
        'createTransactionRequest',
        self._prepare_authorization_transaction_request('authCaptureTransaction', tx_data, tx)
    )

    result = self._format_response(response, 'auth_capture')
    errors = response.get('transactionResponse', {}).get('errors')
    if errors:
        result['x_response_reason_text'] = '\n'.join([e.get('errorText') for e in errors])
    return result

AuthorizeAPI._prepare_authorization_transaction_request = _prepare_authorization_transaction_request
AuthorizeAPI.auth_and_capture = auth_and_capture
AuthorizeAPI.authorize = authorize


class AuthorizeAPI(AuthorizeAPI):

    def __init__(self, provider):
        super(AuthorizeAPI, self).__init__(provider.sudo())

    @api.model
    def text_from_html(
        self, html_content):
        try:
            doc = html.fromstring(html_content)
        except (TypeError, etree.XMLSyntaxError, etree.ParserError):
            _logger.exception("Failure parsing this HTML:\n%s", html_content)
            return ""
        words = u"".join(doc.xpath("//text()")).split()
        text = u" ".join(words)
        return text

    def get_merchant_details(self):

        response = self._make_request('getMerchantDetailsRequest')

        if response and response.get('err_code'):
            raise UserError(_(
                "Authorize.net Error:\nCode: %s\nMessage: %s"
                % (self.AUTH_ERROR_STATUS, response.get('err_msg'))
            ))

        return {
            'resultCode': response.get('messages').get('resultCode'),
            'x_currency': response.get('currencies'),
        }

    def create_customer_profile(self, partner, transaction_id, merchant):
        response = self._make_request('createCustomerProfileFromTransactionRequest', {
            'transId': transaction_id,
            'customer': {
                'merchantCustomerId': merchant,
                'email': partner.email or ''
            }
        })

        if not response.get('customerProfileId'):
            _logger.warning(
                'Unable to create customer payment profile, data missing from transaction. Transaction_id: %s - Partner_id: %s',
                transaction_id, partner,
            )
            return False

        res = {
            'profile_id': response.get('customerProfileId'),
            'payment_profile_id': response.get('customerPaymentProfileIdList', False) and response.get('customerPaymentProfileIdList')[0],
            'shipping_address_id': response.get('customerShippingAddressIdList', False) and response.get('customerShippingAddressIdList')[0]
        }

        response = self._make_request('getCustomerPaymentProfileRequest', {
            'customerProfileId': res['profile_id'],
            'customerPaymentProfileId': res['payment_profile_id'],
        })

        payment = response.get('paymentProfile', {}).get('payment', {})
        res.update(payment=payment)

        return res

    def create_authorize_customer_profile(self, partner, merchant, shipping):
        values = {
            'profile': {
                'merchantCustomerId': merchant,
                'email': partner.email or '',
                'shipToList': {
                    'firstName': shipping.get('first_name'),
                    'lastName': shipping.get('last_name'),
                    'address': shipping.get('address'),
                    'city': shipping.get('city'),
                    'state': shipping.get('state') or None,
                    'zip': shipping.get('zip') or '',
                    'country': shipping.get('country') or None,
                    'phoneNumber': shipping.get('phone_number'),
                },
            }
        }

        response = self._make_request('createCustomerProfileRequest', values)

        if response and response.get('err_code'):
            raise UserError(_(
                "Authorize.net Error:\nCode: %s\nMessage: %s"
                % (response.get('err_code'), response.get('err_msg'))
            ))

        return {
            'profile_id': response.get('customerProfileId'),
            'shipping_address_id': response.get('customerShippingAddressIdList')[0],
        }

    def update_customer_profile(self, partner):
        values = {
            'profile': {
                'merchantCustomerId': partner.merchant_id,
                'email': partner.partner_id.email or '',
                'customerProfileId': partner.customer_profile_id,
            },
        }
        response = self._make_request('updateCustomerProfileRequest', values)

        if response and response.get('err_code'):
            raise UserError(_(
                "Authorize.net Error:\nCode: %s\nMessage: %s"
                % (response.get('err_code'), response.get('err_msg'))
            ))

        return {
            'result_code': response.get('messages').get('resultCode'),
        }

    def update_customer_profile_shipping_address(self, partner, shipping):
        values = {
            'customerProfileId': partner.customer_profile_id,
            'address': {
                'firstName': shipping.get('first_name'),
                'lastName': shipping.get('last_name'),
                'address': shipping.get('address'),
                'city': shipping.get('city'),
                'state': shipping.get('state') or None,
                'zip': shipping.get('zip') or '',
                'country': shipping.get('country') or None,
                'phoneNumber': shipping.get('phone_number'),
                'customerAddressId': partner.shipping_address_id,
            },
        }

        response = self._make_request('updateCustomerShippingAddressRequest', values)

        if response and response.get('err_code'):
            raise UserError(_(
                "Authorize.net Error:\nCode: %s\nMessage: %s"
                % (response.get('err_code'), response.get('err_msg'))
            ))

        return {
            'result_code': response.get('messages').get('resultCode'),
        }

    def unlink_customer_profile(self, partner):
        values = {
            'customerProfileId': partner.customer_profile_id,
        }

        response = self._make_request('deleteCustomerProfileRequest', values)

        if response and response.get('err_code'):
            raise UserError(_(
                "Authorize.net Error:\nCode: %s\nMessage: %s"
                % (response.get('err_code'), response.get('err_msg'))
            ))

        return {
            'result_code': response.get('messages').get('resultCode'),
        }

    def create_customer_payment_profile(self, partner, customer_profile_id, tx=None, billing=None, card_details=None, bank_details=None, opaque_data=None):
        values = {
            'customerProfileId': customer_profile_id,
            'paymentProfile': {
                'billTo': {},
                'payment': {},
            },
            'validationMode': 'liveMode' if self.state == 'enabled' else 'testMode'
        }
        if billing:
            values['paymentProfile']['billTo'].update({
                    'firstName': billing.get('first_name'),
                    'lastName': billing.get('last_name'),
                    'address': billing.get('address'),
                    'city': billing.get('city'),
                    'state': billing.get('state') or None,
                    'zip': billing.get('zip') or '',
                    'country': billing.get('country') or None,
                    'phoneNumber': billing.get('phone_number'),
            })
        elif tx:
            partner_name = ''
            if tx.partner_id and tx.partner_id.name:
                partner_name = tx.partner_id.name
            elif tx.partner_id.parent_id and tx.partner_id.parent_id.name:
                partner_name = tx.partner_id.parent_id.name

            split_name = _partner_split_name(partner_name)
            values['paymentProfile']['billTo'].update({
                'firstName': '' if tx.partner_id.is_company else (split_name and split_name[0][:50] or ''),
                'lastName': split_name and split_name[1] or ' ',  # lastName is always required
                'company': tx.partner_name if tx.partner_name and tx.partner_id.is_company else '',
                'address': tx.partner_address or '',
                'city': tx.partner_city or '',
                'state': tx.partner_state_id.name or '',
                'zip': tx.partner_zip or '',
                'country': tx.partner_country_id.name or '',
            })
        if card_details:
            values['paymentProfile']['payment'].update({
                'creditCard': {
                    'cardNumber': card_details.get('card_number'),
                    'expirationDate': card_details.get('expiry_date'),
                    'cardCode': card_details.get('card_code'),
                }
            })
        elif bank_details:
            values['paymentProfile']['payment'].update({
                'bankAccount': {
                    'accountType': bank_details.get('accountType'),
                    'routingNumber': bank_details.get('routingNumber'),
                    'accountNumber': bank_details.get('accountNumber'),
                    'nameOnAccount': bank_details.get('nameOnAccount'),
                    'bankName': bank_details.get('bankName')
                }
            })
        elif opaque_data:
            values['paymentProfile']['payment'].update({
                'opaqueData': opaque_data
            })
        response = self._make_request('createCustomerPaymentProfileRequest', values)
        if response and response.get('err_code'):
            raise UserError(_(
                "Authorize.net Error:\nCode: %s\nMessage: %s"
                % (response.get('err_code'), response.get('err_msg'))
            ))

        return {
            'customerPaymentProfileId': response.get('customerPaymentProfileId'),
            'customerProfileId': response.get('customerProfileId')
        }

    def get_customer_payment_profile(self, customer_profile_id, payment_profile_id):
        values = {
            'customerProfileId': customer_profile_id,
            'customerPaymentProfileId': payment_profile_id,
        }

        response = self._make_request('getCustomerPaymentProfileRequest', values)

        if response and response.get('err_code'):
            raise UserError(_(
                "Authorize.net Error:\nCode: %s\nMessage: %s"
                % (response.get('err_code'), response.get('err_msg'))
            ))

        return response

    def create_payment_profile_from_tx(self, transId, customer_profile_id):
        values = {
            'transId': transId,
            'customerProfileId': customer_profile_id,
        }
        response = self._make_request('createCustomerProfileFromTransactionRequest', values)

        if response and response.get('err_code'):
            raise UserError(_(
                "Authorize.net Error:\nCode: %s\nMessage: %s"
                % (response.get('err_code'), response.get('err_msg'))
            ))

        return response

    def validate_customer_payment_profile(self, customer_profile_id, payment_profile_id):
        values = {
            'customerProfileId': customer_profile_id,
            'customerPaymentProfileId': payment_profile_id,
            'validationMode': 'liveMode' if self.state == 'enabled' else 'testMode'
        }

        response = self._make_request('validateCustomerPaymentProfileRequest', values)

        if response and response.get('err_code'):
            raise UserError(_(
                "Authorize.net Error:\nCode: %s\nMessage: %s"
                % (response.get('err_code'), response.get('err_msg'))
            ))

        return {
            'result_code': response.get('messages').get('resultCode'),
        }

    def update_customer_payment_profile(self, partner, billing, customer_profile_id, payment_profile_id, card_details=None, bank_details=None):
        values = {
            'customerProfileId': customer_profile_id,
            'paymentProfile': {
                'billTo': {
                    'firstName': billing.get('first_name'),
                    'lastName': billing.get('last_name'),
                    'address': billing.get('address'),
                    'city': billing.get('city'),
                    'state': billing.get('state') or None,
                    'zip': billing.get('zip') or '',
                    'country': billing.get('country') or None,
                    'phoneNumber': billing.get('phone_number'),
                },
                'payment': {},
                'customerPaymentProfileId': payment_profile_id,
            },
            'validationMode': 'liveMode' if self.state == 'enabled' else 'testMode'
        }
        if card_details:
            values['paymentProfile']['payment'].update({
                'creditCard': {
                    'cardNumber': card_details.get('card_number'),
                    'expirationDate': card_details.get('expiry_date'),
                    'cardCode': card_details.get('card_code'),
                }
            })
        elif bank_details:
            values['paymentProfile']['payment'].update({
                'bankAccount': {
                    'accountType': bank_details.get('accountType'),
                    'routingNumber': bank_details.get('routingNumber'),
                    'accountNumber': bank_details.get('accountNumber'),
                    'nameOnAccount': bank_details.get('nameOnAccount'),
                    'bankName': bank_details.get('bankName')
                }
            })
        response = self._make_request('updateCustomerPaymentProfileRequest', values)

        if response and response.get('err_code'):
            raise UserError(_(
                "Authorize.net Error:\nCode: %s\nMessage: %s"
                % (response.get('err_code'), response.get('err_msg'))
            ))

        return {
            'result_code': response.get('messages').get('resultCode'),
        }

    def unlink_customer_payment_profile(self, customer_profile_id, payment_profile_id):
        values = {
            'customerProfileId': customer_profile_id,
            'customerPaymentProfileId': payment_profile_id
        }

        response = self._make_request('deleteCustomerPaymentProfileRequest', values)

        if response and response.get('err_code'):
            raise UserError(_(
                "Authorize.net Error:\nCode: %s\nMessage: %s"
                % (response.get('err_code'), response.get('err_msg'))
            ))

        return {
            'result_code': response.get('messages').get('resultCode'),
        }

    def authorize_charge(self, charge_data):
        values = {
            'refId': charge_data.get('refId'),
            }
        description = self.text_from_html(charge_data.get('description'))
        if charge_data.get('cc_number') and charge_data.get('expiry_date') and charge_data.get('cc_cvv') and charge_data.get('billing'):
            transactionRequest = {
                'transactionRequest': {
                    'transactionType': 'authOnlyTransaction',
                    'amount': charge_data.get('amount'),
                    'payment': {
                        "creditCard": {
                            "cardNumber": charge_data['cc_number'],
                            "expirationDate": charge_data['expiry_date'],
                            "cardCode": charge_data['cc_cvv']
                        },
                    },
                    'order': {
                        'invoiceNumber': charge_data.get('invoiceNumber'),
                        'description': description[:254] + '/' if description and len(description) > 255 else (description or ''),
                    },
                    'lineItems': charge_data.get('line_items'),
                    'billTo': {
                        'firstName': charge_data['billing'].get('first_name'),
                        'lastName': charge_data['billing'].get('last_name'),
                        'address': charge_data['billing'].get('address'),
                        'city': charge_data['billing'].get('city'),
                        'state': charge_data['billing'].get('state') or None,
                        'zip': charge_data['billing'].get('zip') or '',
                        'country': charge_data['billing'].get('country') or None,
                        'phoneNumber': charge_data['billing'].get('phone_number'),
                    },
                }
            }
            values.update(transactionRequest)
        elif charge_data.get('customer_profile_id') and charge_data.get('token'):
            transactionRequest = {
                'transactionRequest': {
                    'transactionType': 'authOnlyTransaction',
                    'amount': charge_data.get('amount'),
                    'profile': {
                        'customerProfileId': charge_data.get('customer_profile_id'),
                        'paymentProfile': {
                            'paymentProfileId': str(charge_data.get('token').provider_ref),
                        }
                    },
                    'order': {
                        'invoiceNumber': charge_data.get('invoiceNumber'),
                        'description': description[:254] + '/' if description and len(description) > 255 else (description or ''),
                    },
                    'lineItems': charge_data.get('line_items'),
                }
            }
            values.update(transactionRequest)
        if charge_data.get('shipping_address_id'):
            shipping_address_id = charge_data['shipping_address_id']
            address =  "%s \n %s \n %s" % (
                         shipping_address_id.street or '',
                         shipping_address_id.street2 or '',
                         shipping_address_id.city or '')

            partner_name = ''
            if shipping_address_id and shipping_address_id.name:
                partner_name = shipping_address_id.name
            elif shipping_address_id.parent_id and shipping_address_id.parent_id.name:
                partner_name = shipping_address_id.parent_id.name

            split_name = _partner_split_name(partner_name)
            city = shipping_address_id.city or ''
            state = shipping_address_id.state_id.code or ''
            shipping_zip = shipping_address_id.zip or ''
            country = shipping_address_id.country_id.code or ''

            values.get('transactionRequest').update(
                shipTo={
                    'firstName': split_name[0] and split_name[0][:50] or '',
                    'lastName': split_name[1] and split_name[1][:50] or '',
                    'address': address and address[:60] or '',
                    'city': city and city[:40] or '',
                    'state': state and state[:40] or '',
                    'zip': shipping_zip and shipping_zip[:20] or '',
                    'country': country and country[:60] or '',
                }
            )
        response = self._make_request('createTransactionRequest', values)
        if response and response.get('err_code'):
            raise UserError(_(
                "Authorize.net Error:\nCode: %s\nMessage: %s"
                % (self.AUTH_ERROR_STATUS, response.get('err_msg'))
            ))

        result = {
            'x_response_code': response.get('transactionResponse', {}).get('responseCode'),
            'x_trans_id': response.get('transactionResponse', {}).get('transId'),
            'x_type': 'auth_only'
        }

        messages = response.get('transactionResponse', {}).get('messages')
        if messages:
            result['x_response_reason_text'] = '\n'.join([e.get('description') for e in messages])

        errors = response.get('transactionResponse', {}).get('errors')
        if errors:
            result['x_response_reason_text'] = '\n'.join([e.get('errorText') for e in errors])
        return result

    def auth_and_capture_charge(self, charge_data, card_details=None, bank_details=None):
        values = {
            'refId': charge_data.get('refId') or '',
        }
        description = self.text_from_html(charge_data.get('description'))
        if charge_data.get('billing') and (card_details or bank_details):
            transactionRequest = {
                'transactionRequest': {
                    'transactionType': 'authCaptureTransaction',
                    'amount': charge_data.get('amount'),
                    'payment': {},
                    'order': {
                        'invoiceNumber': charge_data.get('invoiceNumber'),
                        'description': description[:254] + '/' if description and len(description) > 255 else (description or ''),
                    },
                    'lineItems': charge_data.get('line_items'),
                    'billTo': {
                        'firstName': charge_data['billing'].get('first_name'),
                        'lastName': charge_data['billing'].get('last_name'),
                        'address': charge_data['billing'].get('address'),
                        'city': charge_data['billing'].get('city'),
                        'state': charge_data['billing'].get('state') or None,
                        'zip': charge_data['billing'].get('zip') or '',
                        'country': charge_data['billing'].get('country') or None,
                        'phoneNumber': charge_data['billing'].get('phone_number'),
                    },
                }
            }
            if card_details:
                transactionRequest['transactionRequest']['payment'].update({
                    'creditCard': {
                        'cardNumber': card_details.get('card_number'),
                        'expirationDate': card_details.get('expiry_date'),
                        'cardCode': card_details.get('card_code'),
                    }
                })
            elif bank_details:
                transactionRequest['transactionRequest']['payment'].update({
                    'bankAccount': {
                        'accountType': bank_details.get('accountType'),
                        'routingNumber': bank_details.get('routingNumber'),
                        'accountNumber': bank_details.get('accountNumber'),
                        'nameOnAccount': bank_details.get('nameOnAccount'),
                        'bankName': bank_details.get('bankName')
                    }
                })
            values.update(transactionRequest)
        elif charge_data.get('customer_profile_id') and charge_data.get('paymentProfileId'):
            transactionRequest = {
                'transactionRequest': {
                    'transactionType': 'authCaptureTransaction',
                    'amount': charge_data.get('amount'),
                    'profile': {
                        'customerProfileId': charge_data.get('customer_profile_id'),
                        'paymentProfile': {
                            'paymentProfileId': str(charge_data.get('paymentProfileId')),
                        }
                    },
                    'order': {
                        'invoiceNumber': charge_data.get('invoiceNumber'),
                        'description': description[:254] + '/' if description and len(description) > 255 else (description or ''),
                    },
                    'lineItems': charge_data.get('line_items'),
                }
            }
            values.update(transactionRequest)
        if charge_data.get('shipping_address_id'):
            shipping_address_id = charge_data['shipping_address_id']
            address =  "%s \n %s \n %s" % (
                         shipping_address_id.street or '',
                         shipping_address_id.street2 or '',
                         shipping_address_id.city or '')

            partner_name = ''
            if shipping_address_id and shipping_address_id.name:
                partner_name = shipping_address_id.name
            elif shipping_address_id.parent_id and shipping_address_id.parent_id.name:
                partner_name = shipping_address_id.parent_id.name
            split_name = _partner_split_name(partner_name)

            city = shipping_address_id.city or ''
            state = shipping_address_id.state_id.code or ''
            shipping_zip = shipping_address_id.zip or ''
            country = shipping_address_id.country_id.code or ''
            values.get('transactionRequest').update(
                shipTo={
                    'firstName': split_name[0] and split_name[0][:50] or '',
                    'lastName': split_name[1] and split_name[1][:50] or '',
                    'address': address and address[:60] or '',
                    'city': city and city[:40] or '',
                    'state': state and state[:40] or '',
                    'zip': shipping_zip and shipping_zip[:20] or '',
                    'country': country and country[:60] or '',
                }
            )

        response = self._make_request('createTransactionRequest', values)
        if response and response.get('err_code'):
            raise UserError(_(
                "Authorize.net Error:\nCode: %s\nMessage: %s"
                % (self.AUTH_ERROR_STATUS, response.get('err_msg'))
            ))

        result = {
            'x_response_code': response.get('transactionResponse', {}).get('responseCode'),
            'x_trans_id': response.get('transactionResponse', {}).get('transId'),
            'x_type': 'auth_capture'
        }

        messages = response.get('transactionResponse', {}).get('messages')
        if messages:
            result['x_response_reason_text'] = '\n'.join([e.get('description') for e in messages])

        errors = response.get('transactionResponse', {}).get('errors')
        if errors:
            result['x_response_reason_text'] = '\n'.join([e.get('errorText') for e in errors])
        return result

    def capture(self, transaction_id, amount):
        """ overwrite method because of amount element must be write below on transaction type. """
        values = {
            'transactionRequest': {
                'transactionType': 'priorAuthCaptureTransaction',
                'amount': str(amount),
                'refTransId': transaction_id
            }
        }

        response = self._make_request('createTransactionRequest', values)

        if response and response.get('err_code'):
            return {
                'x_response_code': self.AUTH_ERROR_STATUS,
                'x_response_reason_text': response.get('err_msg')
            }

        result = {
            'x_response_code': response.get('transactionResponse', {}).get('responseCode'),
            'x_trans_id': response.get('transactionResponse', {}).get('transId'),
            'x_type': 'prior_auth_capture'
        }

        messages = response.get('transactionResponse', {}).get('messages')
        if messages:
            result['x_response_reason_text'] = '\n'.join([e.get('description') for e in messages])

        errors = response.get('transactionResponse', {}).get('errors')
        if errors:
            result['x_response_reason_text'] = '\n'.join([e.get('errorText') for e in errors])
        return result

    def refund_transaction(self, charge_data):
        values = {
            'refId': charge_data.get('refId'),
            }
        description = self.text_from_html(charge_data.get('description'))
        if charge_data.get('cc_number') and charge_data.get('expiry_date'):
            transactionRequest = {
                'transactionRequest': {
                    'transactionType': 'refundTransaction',
                    'amount': charge_data.get('amount'),
                    'payment': {
                        "creditCard": {
                            "cardNumber": charge_data['cc_number'],
                            "expirationDate": charge_data['expiry_date'],
                        },
                    },
                    'refTransId': charge_data.get('trans_id'),
                    'order': {
                        'invoiceNumber': charge_data.get('invoiceNumber'),
                        'description': description[:254] + '/' if description and len(description) > 255 else (description or ''),
                    },
                }
            }
            values.update(transactionRequest)

        response = self._make_request('createTransactionRequest', values)

        if response and response.get('err_code'):
            raise UserError(_(
                "Authorize.net Error:\nCode: %s\nMessage: %s"
                % (self.AUTH_ERROR_STATUS, response.get('err_msg'))
            ))

        result = {
            'x_response_code': response.get('transactionResponse', {}).get('responseCode'),
            'x_trans_id': response.get('transactionResponse', {}).get('transId'),
            'x_type': 'auth_capture'
        }

        messages = response.get('transactionResponse', {}).get('messages')
        if messages:
            result['x_response_reason_text'] = '\n'.join([e.get('description') for e in messages])

        errors = response.get('transactionResponse', {}).get('errors')
        if errors:
            result['x_response_reason_text'] = '\n'.join([e.get('errorText') for e in errors])

        return result

    def get_transaction_details(self, transaction_id, backend=False):
        response = self._make_request('getTransactionDetailsRequest', {'transId': transaction_id})
        if backend and response and response.get('err_code'):
            raise UserError(_(
                "Authorize.net Error:\nCode: %s\nMessage: %s"
                % (self.AUTH_ERROR_STATUS, response.get('err_msg'))
            ))
        return response
