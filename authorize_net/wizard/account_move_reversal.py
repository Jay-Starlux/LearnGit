# -*- coding: utf-8 -*-
# Part of Odoo. See COPYRIGHT & LICENSE files for full copyright and licensing details.

from odoo import models


class AccountMoveReversal(models.TransientModel):
    """Account move reversal wizard, it cancel an account move by reversing it.
    """
    _inherit = "account.move.reversal"

    def _prepare_default_reversal(self, move):
        values = super(AccountMoveReversal, self)._prepare_default_reversal(move)
        values.update({'transaction_ids': [(6, 0, move.transaction_ids.ids)] if move.transaction_ids else False})
        return values
