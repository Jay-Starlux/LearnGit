# -*- coding: utf-8 -*-
# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.

from odoo import fields, models, api, _
from odoo.addons.payment import utils as payment_utils


class AccountMove(models.Model):
    _inherit = "account.move"

    def payment_action_capture(self):
        """ Capture all transactions linked to this invoice. """
        payment_utils.check_rights_on_recordset(self)
        authorized_transaction_ids = self.authorized_transaction_ids
        result = self.authorized_transaction_ids.sudo().action_capture()
        self.authorized_transaction_ids._cron_finalize_post_processing()
        authorized_transaction_ids = authorized_transaction_ids.filtered(lambda x: x.state == 'done' and x.payment_id)
        if not self.authorized_transaction_ids and authorized_transaction_ids:
            for tx in authorized_transaction_ids:
                if tx.payment_id and tx.provider_id.code == 'authorize':
                    tx.payment_id.authorize_payment_type = "credit_card" if tx.payment_method_id.id == self.env.ref("payment.payment_method_card").id else "bank_account"
                    tx.payment_id.payment_method_type_id = tx.payment_method_id.id

                if tx.payment_id.state == 'draft':
                    tx.payment_id.action_post()
                (tx.payment_id.line_ids + tx.invoice_ids.line_ids).filtered(
                    lambda line: line.account_id == tx.payment_id.destination_account_id
                    and not line.reconciled
                ).reconcile()
                tx.is_post_processed = True
        return result
