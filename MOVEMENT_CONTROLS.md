# Movement controls

Shared tables, main content, modal content and report tables now expose left/right scroll buttons when their content exceeds the available width. Arrow keys work while the scrolling region is focused. Buttons disable at the corresponding edge; reduced-motion preferences are respected. Print/PDF output excludes these controls and removes scrolling constraints.

Shared modal headers support pointer dragging and keyboard arrow movement through the focusable title. Home and the Center button restore the original position. Movement is constrained to the viewport; resizing resets placement. Form values and document authorization rules are unchanged.

Validation: frontend production build and route integrity passed (39 lazy imports, 43 routes, 88 navigation targets). An isolated browser check exercised horizontal scrolling, keyboard window movement, centering and pointer dragging successfully.
