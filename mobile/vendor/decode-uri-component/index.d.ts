/**
Decodes a Uniform Resource Identifier (URI) component previously created by `encodeURIComponent()`
or by a similar routine (OPSYS CommonJS adaptation of decode-uri-component 0.5.1).
*/
declare function decodeUriComponent(encodedURI: string): string;
declare namespace decodeUriComponent {
	export {decodeUriComponent as default};
}
export = decodeUriComponent;
