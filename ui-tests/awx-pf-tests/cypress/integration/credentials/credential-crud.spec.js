/**
 * Tests for basic operations on credentials and credential lists.
 */

context.skip('Advanced search on credentials', function() {})
context.skip('Empty list of credentials', function() {
  it('Shows the add button when there is an empty list of credentials', function() {})
})

context('Credential Lists', function() {
  // See tips and tricks section in the README for elaboration on
  // why we build for-loops with premade arrays
  let arr5 = Array.from({ length: 5 }, (v, k) => k + 1) // Small array
  let arr21 = Array.from({ length: 21 }, (v, k) => k + 1) // Min size for two pages of data

  context('Single-credential operations', function() {
    beforeEach(function() {
      cy.createOrReplace('credentials', 'test-credential-list').as('cred')
      cy.visit('/#/credentials/')
      cy.get('input[type=search]').type('test-credential-list')
      cy.get('[aria-label="Search submit button"]').click()
    })

    it('can visit a credential link', function() {
      cy.get(`[href="#/credentials/${this.cred.id}/details"]`).click()
      cy.url().should('include', `/#/credentials/${this.cred.id}/details`)
    })
  })

  context('Multi-credential operations', function() {
    beforeEach(function() {
      cy.wrap(arr5).each(function(i) {
        cy.createOrReplace('credentials', `test-credentials-${i}`).as(`cred${i}`)
      })

      cy.visit('/#/credentials')
      cy.get('input[type=search]').type('test-credentials-')
      cy.get('[aria-label="Search submit button"]').click()
    })

    it('can select multiple credentials in a list and delete them', function() {
      // Iterate and click each item in the list
      cy.wrap(arr5).each(function(i) {
        cy.get(`#select-credential-${this[`cred${i}`].id}`).click()
      })
      cy.get('button[aria-label=Delete]').click()

      // Assert that the list of items to be deleted is correct
      cy.wrap(arr5).each(function(i) {
        cy.get('.pf-c-modal-box')
          .contains(`test-credentials-${i}`)
          .should('be.visible')
      })

      // Delete items
      cy.get('[aria-label="confirm delete"]').click()

      // Confirm deletion
      cy.get('.pf-c-empty-state').should('be.visible')
    })

    it('can delete two different sets of credentials in succession', function() {
      // Choose first set of items to be deleted
      cy.get(`#select-credential-${this['cred1'].id}`).click()
      cy.get(`#select-credential-${this['cred2'].id}`).click()
      cy.get('button[aria-label=Delete]').click()

      // Assert that the first deletion has the correct items
      cy.get('.pf-c-modal-box').within(() => {
        cy.contains('test-credentials-1').should('be.visible')
        cy.contains('test-credentials-2').should('be.visible')
      })

      // Confirm that the correct items were deleted
      cy.get('[aria-label="confirm delete"]').click()
      cy.get('[aria-label="Items List"]').within(() => {
        cy.contains('test-credentials-1').should('not.exist')
        cy.contains('test-credentials-2').should('not.exist')
        cy.contains('test-credentials-3').should('be.visible')
        cy.contains('test-credentials-4').should('be.visible')
      })

      // Second deletion
      cy.get(`#select-credential-${this['cred3'].id}`).click()
      cy.get(`#select-credential-${this['cred4'].id}`).click()
      cy.get('button[aria-label=Delete]').click()

      // Confirm that a different set of items is to be deleted
      cy.get('.pf-c-modal-box').within(() => {
        cy.contains('test-credentials-1').should('not.exist')
        cy.contains('test-credentials-2').should('not.exist')
        cy.contains('test-credentials-3').should('be.visible')
        cy.contains('test-credentials-4').should('be.visible')
      })
      cy.get('[aria-label="confirm delete"]').click()

      // Confirm all items successfully deleted
      cy.get('[aria-label="Items List"]').within(() => {
        cy.contains('test-credentials-1').should('not.exist')
        cy.contains('test-credentials-2').should('not.exist')
        cy.contains('test-credentials-3').should('not.exist')
        cy.contains('test-credentials-4').should('not.exist')
      })
    })

    it.skip('can search and sort the credential list', function() {})
    // TODO: Waiting on search implementation
  })

  context('Credential pagination', function() {
    beforeEach(function() {
      cy.wrap(arr21).each(function(i) {
        cy.akit(`credentials.get_or_create(name="cred-pagination-${i}")`).as(`cred${i}`)
      })
      cy.visit('/#/credentials')
      cy.get('input[type=search]').type('cred-pagination-')
      cy.get('[aria-label="Search submit button"]').click()
    })
    it('Can navigate to the second page', function() {
      cy.get('[data-action=next]').click()
      cy.get('[aria-label="Items List"]').within(() => {
        cy.contains('cred-pagination-9').should('be.visible')
      })
      cy.get('[aria-label="Current page"]').should('have.attr', 'value', '2')
    })

    // https://github.com/ansible/awx/issues/4239
    it.skip('Can delete items on the second page and revert to the first page', function() {
      cy.get('[data-action=next]').click()
      cy.get(`#select-credential-${this['cred9'].id}`).click()
      cy.get('button[aria-label=Delete]').click()
      cy.get('.pf-c-modal-box').within(() => {
        cy.contains('test-credentials-9').should('not.exist')
      })
      cy.get('[aria-label="confirm delete"]').click()
      cy.get('[aria-label="Current page"]').should('have.attr', 'value', '1')
    })
    it('Can toggle the amount of visible items in the credential list', function() {
      // 5 visible items
      cy.get('[id*="pagination-options-menu-toggle"]').click()
      cy.get('[data-action="per-page-5"]').click()
      cy.get('[aria-label="Items List"]')
        .find('li')
        .should('have.length', 5)

      // 10 visible items
      cy.get('[id*="pagination-options-menu-toggle"]').click()
      cy.get('[data-action="per-page-10"]').click()
      cy.get('[aria-label="Items List"]')
        .find('li')
        .should('have.length', 10)

      // 20 visible items
      cy.get('[id*="pagination-options-menu-toggle"]').click()
      cy.get('[data-action="per-page-20"]').click()
      cy.get('[aria-label="Items List"]')
        .find('li')
        .should('have.length', 20)

      // Only 21 items available, so expect 21
      cy.get('[id*="pagination-options-menu-toggle"]').click()
      cy.get('[data-action="per-page-50"]').click()
      cy.get('[aria-label="Items List"]')
        .find('li')
        .should('have.length', 21)
    })
  })
})
