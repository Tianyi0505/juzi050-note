%option noyywrap
%{
#include <stdio.h>
%}
%%
[0-9]+       { printf("INT: %s\n", yytext); }
[ \t\r\n]+  { /* skip whitespace */ }
.            { /* skip other characters */ }
%%
int main(void) { yylex(); return 0; }
